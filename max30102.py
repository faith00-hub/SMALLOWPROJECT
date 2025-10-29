# max30102.py
from time import sleep_ms

class MAX30102:
    """Driver dasar untuk sensor MAX30102 Detak Jantung dan SpO2."""

    I2C_ADDR = 0x57
    
    # Register Addresses
    REG_MODE_CONFIG   = 0x09
    REG_FIFO_DATA     = 0x07
    REG_FIFO_CONFIG   = 0x08
    REG_SPO2_CONFIG   = 0x0A
    REG_LED_CONFIG    = 0x0C
    
    MODE_HR_SPO2 = 0x03 # Mode SpO2 (Red dan IR)

    def __init__(self, i2c):
        """Inisialisasi sensor MAX30102."""
        self.i2c = i2c
        self.addr = self.I2C_ADDR
        
        if self.addr not in self.i2c.scan():
            raise OSError(f"MAX30102 not found at I2C address {hex(self.addr)}. Check wiring.")

        # 1. Reset chip dan Konfigurasi
        self._write_register(self.REG_MODE_CONFIG, 0x40) # Reset
        sleep_ms(100) 
        self._write_register(self.REG_FIFO_CONFIG, 0x4F) # FIFO Config
        self._write_register(self.REG_MODE_CONFIG, self.MODE_HR_SPO2) # SpO2 Mode
        self._write_register(self.REG_SPO2_CONFIG, 0x27) # Sample Rate/Resolution
        self._write_register(self.REG_LED_CONFIG, 0x1F) # LED Current
        
        print("MAX30102: Initialized.")

    def _write_register(self, reg, value):
        """Menulis nilai ke register."""
        self.i2c.writeto(self.addr, bytearray([reg, value]))

    def _read_register(self, reg, num_bytes):
        """Membaca nilai dari register."""
        self.i2c.writeto(self.addr, bytearray([reg]))
        return self.i2c.readfrom(self.addr, num_bytes)
    
    def read_fifo(self):
        """
        Membaca 6 byte data dari FIFO (3 byte Red, 3 byte IR).
        
        Returns:
            Tuple (red_data, ir_data)
        """
        data = self._read_register(self.REG_FIFO_DATA, 6)

        red_led = (data[0] << 16) | (data[1] << 8) | data[2]
        ir_led = (data[3] << 16) | (data[4] << 8) | data[5]
        
        # Masking untuk mengambil hanya 18 bit
        red_data = red_led & 0x3FFFF
        ir_data = ir_led & 0x3FFFF
        
        return red_data, ir_data