import json
import math
import struct
import threading
import time
from pathlib import Path
from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.textinput import TextInput
from kivy.uix.button import Button
from kivy.uix.spinner import Spinner
from kivy.utils import platform

# Android platformunda calisiyorsa gerekli izinleri ve Java siniflarini ice aktar
if platform == 'android':
    from android.permissions import request_permissions, Permission
    from jnius import autoclass, PythonJavaClass, java_method

    # BLE reklam (yayin) durumunu takip eden ozel Java geri cagirma sinifi
    class MyAdvertiseCallback(PythonJavaClass):
        __javainterfaces__ = ['android/bluetooth/le/AdvertiseCallback']
        __javacontext__ = 'app'

        @java_method('(I)V')
        def onStartFailure(self, errorCode):
            print("BLE Yayin Hatasi Kodu:", errorCode)

        @java_method('(Landroid/bluetooth/le/AdvertiseSettings;)V')
        def onStartSuccess(self, settingsInEffect):
            print("BLE Yayini Basariyla Basladi")

# Ad Soyad girisini Bluetooth paket boyutuna sigmasi icin 10 karakterle sinirlayan kutu
class SinirliTextInput(TextInput):
    def insert_text(self, substring, from_undo=False):
        kalan = 10 - len(self.text)
        if kalan > 0:
            super().insert_text(substring[:kalan], from_undo=from_undo)

class KazazedeApp(App):
    def build(self):
        # Kullanici bilgilerinin kaydedilecegi yerel JSON dosya yolu
        self.dosya_yolu = Path(self.user_data_dir) / "profil_data.json"
        self.yayin_aktif = False
        self.siren_aktif = False
        self.advertiser = None
        self.callback = None
        self.wake_lock = None

        layout = BoxLayout(orientation='vertical', padding=20, spacing=15)

        # Android 12+ Bluetooth, Ses, Uyku Kilidi ve Bildirim izinlerini iste
        if platform == 'android':
            izinler = [
                Permission.BLUETOOTH_CONNECT,
                Permission.BLUETOOTH_ADVERTISE,
                Permission.ACCESS_FINE_LOCATION,
                Permission.MODIFY_AUDIO_SETTINGS,
                Permission.WAKE_LOCK
            ]
            if hasattr(Permission, 'POST_NOTIFICATIONS'):
                izinler.append(Permission.POST_NOTIFICATIONS)
            if hasattr(Permission, 'FOREGROUND_SERVICE'):
                izinler.append(Permission.FOREGROUND_SERVICE)
            request_permissions(izinler)

        # Arayuz bilesenlerinin olusturulmasi
        self.ad_input = SinirliTextInput(hint_text="Ad Soyad (Maks. 10 Karakter)", multiline=False)
        self.kan_spinner = Spinner(
            text='Kan Grubu Seciniz',
            values=('0rh+', '0rh-', 'arh+', 'arh-', 'brh+', 'brh-', 'abrh+', 'abrh-'),
            size_hint=(1, None), size=(100, 44)
        )

        self.sos_buton = Button(
            text="SOS YAYININI BASLAT",
            background_color=(0.8, 0.1, 0.1, 1), font_size=20, bold=True
        )
        self.sos_buton.bind(on_press=self.sos_tetikle)

        self.siren_buton = Button(
            text="ACIL DUDUK / SIREN CAL (3500 Hz)",
            background_color=(0.9, 0.5, 0.0, 1), font_size=18, bold=True
        )
        self.siren_buton.bind(on_press=self.siren_tetikle)

        layout.add_widget(Label(text="KAZAZEDE ACIL SINYAL PANELI", font_size=22, bold=True))
        layout.add_widget(self.ad_input)
        layout.add_widget(self.kan_spinner)
        layout.add_widget(self.sos_buton)
        layout.add_widget(self.siren_buton)

        # Daha once kaydedilmis profil varsa otomatik yukle
        self.profil_yukle()
        return layout

    def profil_yukle(self):
        if self.dosya_yolu.exists():
            try:
                data = json.loads(self.dosya_yolu.read_text(encoding="utf-8"))
                self.ad_input.text = data.get("ad", "")[:10]
                self.kan_spinner.text = data.get("kan", "Kan Grubu Seciniz")
            except:
                pass

    # Turkce karakterleri temizler ve her harfi ASCII tablosunda 1 kaydirarak maskeler
    def veri_maskele(self, metin):
        temiz = metin.lower()
        degisim = {"ı": "i", "ğ": "g", "ü": "u", "ş": "s", "ö": "o", "ç": "c"}
        for tr, en in degisim.items():
            temiz = temiz.replace(tr, en)

        sonuc = []
        for c in temiz:
            if c == " ":
                sonuc.append("_")
            else:
                sonuc.append(chr(ord(c) + 1))
        return "".join(sonuc)

    # Ekran kapansa bile islemciyi uyanik tutar ve kalici bildirim gosterir
    def arka_plan_korumasi_ac(self):
        if platform != 'android':
            return
        try:
            PythonActivity = autoclass('org.kivy.android.PythonActivity')
            Context = autoclass('android.content.Context')
            PowerManager = autoclass('android.os.PowerManager')
            NotificationBuilder = autoclass('android.app.Notification$Builder')
            NotificationChannel = autoclass('android.app.NotificationChannel')
            NotificationManager = autoclass('android.app.NotificationManager')
            BuildVersion = autoclass('android.os.Build$VERSION')
            String = autoclass('java.lang.String')

            activity = PythonActivity.mActivity

            # CPU uyku kilidini aktif et
            pm = activity.getSystemService(Context.POWER_SERVICE)
            self.wake_lock = pm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, String("Kazazede::SOSLock"))
            if not self.wake_lock.isHeld():
                self.wake_lock.acquire()

            # Ust bildirim cubugunda kapatilamayan kalici bildirim olustur
            nm = activity.getSystemService(Context.NOTIFICATION_SERVICE)
            channel_id = String("sos_acil_kanal")

            if BuildVersion.SDK_INT >= 26:
                channel = NotificationChannel(
                    channel_id,
                    String("Acil Durum SOS Yayini"),
                    NotificationManager.IMPORTANCE_HIGH
                )
                nm.createNotificationChannel(channel)
                builder = NotificationBuilder(activity, channel_id)
            else:
                builder = NotificationBuilder(activity)

            builder.setContentTitle(String("SOS ACIL SINYALI AKTIF"))
            builder.setContentText(String("Konum ve kimlik sinyali yayinlaniyor. Kapatmayin."))
            builder.setSmallIcon(activity.getApplicationInfo().icon)
            builder.setOngoing(True)

            nm.notify(1001, builder.build())
        except Exception as e:
            print("Arka plan koruma hatasi:", e)

    # Yayin durduruldugunda uyku kilidini serbest birakir ve bildirimi kaldirir
    def arka_plan_korumasi_kapat(self):
        if platform != 'android':
            return
        try:
            if self.wake_lock and self.wake_lock.isHeld():
                self.wake_lock.release()

            PythonActivity = autoclass('org.kivy.android.PythonActivity')
            Context = autoclass('android.content.Context')
            nm = PythonActivity.mActivity.getSystemService(Context.NOTIFICATION_SERVICE)
            nm.cancel(1001)
        except:
            pass

    # Acil durum duduk/siren butonunu acar veya kapatir
    def siren_tetikle(self, instance):
        if self.siren_aktif:
            self.siren_aktif = False
            self.siren_buton.text = "ACIL DUDUK / SIREN CAL (3500 Hz)"
            self.siren_buton.background_color = (0.9, 0.5, 0.0, 1)
            return

        self.siren_aktif = True
        self.siren_buton.text = "SIREN CALIYOR (DURDURMAK ICIN BAS)"
        self.siren_buton.background_color = (0.1, 0.6, 0.1, 1)
        threading.Thread(target=self.yuksek_ses_uret, daemon=True).start()

    # Insan kulaginin en hassas oldugu 3500-3800 Hz araliginda kesik siren sesi uretir
    def yuksek_ses_uret(self):
        if platform == 'android':
            try:
                AudioTrack = autoclass('android.media.AudioTrack')
                AudioFormat = autoclass('android.media.AudioFormat')
                AudioManager = autoclass('android.media.AudioManager')
                Context = autoclass('android.content.Context')
                PythonActivity = autoclass('org.kivy.android.PythonActivity')

                # Telefonun alarm ses seviyesini otomatik maksimuma cikar
                activity = PythonActivity.mActivity
                audio_manager = activity.getSystemService(Context.AUDIO_SERVICE)
                max_vol = audio_manager.getStreamMaxVolume(AudioManager.STREAM_ALARM)
                audio_manager.setStreamVolume(AudioManager.STREAM_ALARM, max_vol, 0)

                sample_rate = 16000
                duration = 0.4
                num_samples = int(sample_rate * duration)

                # Sinuzoidal dalga formu ile yuksek frekansli ses tamponu olustur
                buffer = bytearray()
                for i in range(num_samples):
                    freq = 3500 + (300 * (i / num_samples))
                    sample = int(32767 * math.sin(2 * math.pi * freq * i / sample_rate))
                    buffer.extend(struct.pack('<h', sample))

                audio_track = AudioTrack(
                    AudioManager.STREAM_ALARM,
                    sample_rate,
                    AudioFormat.CHANNEL_OUT_MONO,
                    AudioFormat.ENCODING_PCM_16BIT,
                    len(buffer),
                    AudioTrack.MODE_STATIC
                )

                while self.siren_aktif:
                    audio_track.write(bytes(buffer), 0, len(buffer))
                    audio_track.play()
                    time.sleep(0.45)
                    audio_track.stop()
                    audio_track.reloadStaticData()
                    time.sleep(0.15)

                audio_track.release()
            except Exception as e:
                print("Ses hatasi:", e)
        else:
            while self.siren_aktif:
                print("BEEP! [3500 Hz Yuksek Frekansli Siren]")
                time.sleep(0.6)

    # Bluetooth Low Energy (BLE) uzerinden SOS sinyal yayinini baslatir veya durdurur
    def sos_tetikle(self, instance):
        if self.yayin_aktif:
            if platform == 'android' and self.advertiser and self.callback:
                try:
                    self.advertiser.stopAdvertising(self.callback)
                except:
                    pass
            self.arka_plan_korumasi_kapat()
            self.yayin_aktif = False
            self.sos_buton.text = "SOS YAYININI BASLAT"
            self.sos_buton.background_color = (0.8, 0.1, 0.1, 1)
            return

        ad_metni = self.ad_input.text.strip()[:10]
        kan_metni = self.kan_spinner.text

        if not ad_metni or kan_metni == 'Kan Grubu Seciniz':
            self.sos_buton.text = "ALANLARI DOLDURUN!"
            return

        # Kullanici verilerini yerel dosyaya kaydet
        data = {"ad": ad_metni, "kan": kan_metni}
        self.dosya_yolu.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

        maskeli_ad = self.veri_maskele(ad_metni)
        temiz_kan = kan_metni.replace(" ", "_")
        sinyal_adi = f"SOS_{maskeli_ad}_{temiz_kan}"

        if platform == 'android':
            try:
                BluetoothAdapter = autoclass('android.bluetooth.BluetoothAdapter')
                AdvertiseSettings = autoclass('android.bluetooth.le.AdvertiseSettings')
                AdvertiseData = autoclass('android.bluetooth.le.AdvertiseData')

                self.adapter = BluetoothAdapter.getDefaultAdapter()
                if not self.adapter:
                    self.sos_buton.text = "BLUETOOTH BULUNAMADI!"
                    return

                # Bluetooth kapaliysa kullaniciyi uyar
                if not self.adapter.isEnabled():
                    self.sos_buton.text = "ONCE BLUETOOTH'U ACIN!"
                    return

                # Telefonun Bluetooth adini SOS paketi formatina ayarla
                self.adapter.setName(sinyal_adi)
                self.advertiser = self.adapter.getBluetoothLeAdvertiser()

                if self.advertiser:
                    settings = AdvertiseSettings.Builder()                        .setAdvertiseMode(AdvertiseSettings.ADVERTISE_MODE_LOW_LATENCY)                        .setTxPowerLevel(AdvertiseSettings.ADVERTISE_TX_POWER_HIGH)                        .setConnectable(False)                        .build()

                    adv_data = AdvertiseData.Builder()                        .setIncludeDeviceName(True)                        .build()

                    self.callback = MyAdvertiseCallback()
                    self.advertiser.startAdvertising(settings, adv_data, self.callback)
                else:
                    self.sos_buton.text = "CIHAZ BLE DESTEKLEMIYOR!"
                    return
            except Exception as e:
                self.sos_buton.text = "BLUETOOTH HATASI!"
                return

        self.arka_plan_korumasi_ac()
        self.yayin_aktif = True
        self.sos_buton.text = "YAYIN AKTIF (DURDURMAK ICIN BAS)"
        self.sos_buton.background_color = (0.1, 0.6, 0.1, 1)

if __name__ == '__main__':
    KazazedeApp().run()
