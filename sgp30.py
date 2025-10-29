# sgp30.py
from time import sleep_ms, sleep

class SGP30:
    """Driver I2C untuk sensor kualitas udara SGP30 (eCO2 dan TVOC)."""

    I2C_ADDR = 0x58
    CMD_INIT_AIR_QUALITY = 0x2003
    CMD_MEASURE_AIR_QUALITY = 0x2008

    def __init__(self, i2c):
        """Inisialisasi sensor SGP30."""
        self.i2c = i2c
        
        try:
            # Kirim perintah INIT_AIR_QUALITY
            self.i2c.writeto(self.I2C_ADDR, bytearray([0x20, 0x03]))
            sleep_ms(10)
        except OSError:
            raise OSError(f"SGP30 not found at {hex(self.I2C_ADDR)}. Check wiring.")
            
        # Waktu tunggu inisialisasi wajib (15s)
        print("SGP30: Waiting 15s for sensor stabilization...")
        sleep(15) 
        print("SGP30: Ready.")

    def _bytes_to_int(self, data):
        """Menggabungkan dua byte (High dan Low) menjadi integer."""
        return (data[0] << 8) | data[1]
    
    def read_air_quality(self):
        """
        Membaca nilai eCO2 (ppm) dan TVOC (ppb). 
        HARUS dipanggil setiap 1 detik.
        """
        # Kirim perintah MEASURE_AIR_QUALITY
        self.i2c.writeto(self.I2C_ADDR, bytearray([0x20, 0x08]))
        sleep_ms(50)
        
        # Baca 6 byte: [eCO2_H, eCO2_L, eCO2_CRC, TVOC_H, TVOC_L, TVOC_CRC]
        data = self.i2c.readfrom(self.I2C_ADDR, 6)
        
        eCO2 = self._bytes_to_int(data[0:2])
        TVOC = self._bytes_to_int(data[3:5])

        return {'eCO2': eCO2, 'TVOC': TVOC}