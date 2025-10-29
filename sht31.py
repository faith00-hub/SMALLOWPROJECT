# sht31.py - Driver I2C untuk SHT31 Temperature and Humidity Sensor
from time import sleep_ms

class SHT31:
    """Driver I2C untuk SHT31. Menggunakan Mode High Repeatability."""

    I2C_ADDR = 0x44
    
    # Perintah Pengukuran (High Repeatability, Single-shot)
    CMD_MEASURE_HIGH_REP = b'\x24\x00' 
    
    # Perintah Reset dan Clear Status Register
    CMD_SOFT_RESET = b'\x30\xA2'
    CMD_CLEAR_STATUS = b'\x30\xA4'
    
    # Perintah Status Register (untuk debugging)
    CMD_READ_STATUS = b'\xF3\x2D'

    def __init__(self, i2c, addr=I2C_ADDR):
        """Inisialisasi sensor SHT31."""
        self.i2c = i2c
        self.addr = addr
        
        # Jeda lebih panjang untuk stabilitas bus setelah inisialisasi sensor lain
        sleep_ms(50) 
        
        # 1. Coba Soft Reset
        try:
            self.i2c.writeto(self.addr, self.CMD_SOFT_RESET)
            sleep_ms(20) # Waktu tunggu wajib setelah reset
        except OSError as e:
            # Jika Soft Reset gagal, ini adalah masalah hardware
            raise OSError(f"SHT31 (0x{self.addr:x}) soft reset failed: {e}") 

        print(f"SHT31 (0x{self.addr:x}): Initialized successfully via Soft Reset.")


    def _read_raw_data(self):
        """Mengirim perintah pengukuran dan membaca data mentah 6 byte."""
        try:
            # 1. Kirim perintah pengukuran
            self.i2c.writeto(self.addr, self.CMD_MEASURE_HIGH_REP)
            
            # 2. Waktu tunggu yang cukup untuk pengukuran High Repeatability
            sleep_ms(20) 
            
            # 3. Baca 6 byte (Temp MSB, Temp LSB, Temp CRC, Hum MSB, Hum LSB, Hum CRC)
            data = self.i2c.readfrom(self.addr, 6)
            
            temp_raw = (data[0] << 8) | data[1]
            hum_raw = (data[3] << 8) | data[4]
            
            return temp_raw, hum_raw
        except OSError as e:
            raise OSError(f"SHT31 Read Error during data collection: {e}")

    def read_data(self):
        """
        Membaca dan mengkonversi nilai Suhu (°C) dan Kelembaban (%).

        Returns:
            Tuple (temperature_celsius, humidity_percent)
        """
        try:
            temp_raw, hum_raw = self._read_raw_data()
        except OSError as e:
            print(f"SHT31 Communication Error: {e}. Returning default values.")
            return -99.9, -99.9 # Nilai error

        # Konversi Suhu (Celsius): Temp = -45 + 175 * (raw / 65535)
        temperature = -45 + 175 * (temp_raw / 65535)

        # Konversi Kelembaban (RH): Hum = 100 * (raw / 65535)
        humidity = 100 * (hum_raw / 65535)

        return temperature, humidity

    def check_status(self):
        """Membaca dan mencetak Status Register (untuk debugging)."""
        try:
            # Menggunakan readfrom_mem untuk membaca register status
            self.i2c.writeto(self.addr, self.CMD_READ_STATUS)
            data = self.i2c.readfrom(self.addr, 2)
            status = (data[0] << 8) | data[1]
            print(f"SHT31 Status Register: 0x{status:04x}")
            return status
        except OSError as e:
            print(f"SHT31 Status Read Error: {e}")
            return -1