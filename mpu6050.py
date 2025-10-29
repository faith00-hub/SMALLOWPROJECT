# mpu6050.py - Driver I2C untuk sensor IMU MPU6050
from time import sleep_ms

class MPU6050:
    """Driver I2C untuk sensor IMU MPU6050."""

    I2C_ADDR = 0x68
    
    # Register Definitions
    REG_PWR_MGMT_1 = 0x6B
    REG_ACCEL_XOUT_H = 0x3B
    REG_ACCEL_YOUT_H = 0x3D
    REG_ACCEL_ZOUT_H = 0x3F
    REG_GYRO_XOUT_H = 0x43
    REG_GYRO_YOUT_H = 0x45
    REG_GYRO_ZOUT_H = 0x47
    
    # Scaling Factors (Full Scale Range +/- 2g dan +/- 250 deg/s)
    ACCEL_SCALE_MODIFIER = 16384.0 
    GYRO_SCALE_MODIFIER = 131.0

   # MPU6050.py - FUNGSI __init__ (REVISI FINAL)
# ... (pastikan import dan konstanta sama) ...

    def __init__(self, i2c, addr=I2C_ADDR):
        """Inisialisasi sensor MPU6050."""
        self.i2c = i2c
        self.addr = addr
        
        sleep_ms(50) 

        # 1. SOFT RESET: Mengatur bit 7 dari Power Management 1 (TIDAK PAKAI TRY-EXCEPT)
        # Jika ini gagal, error akan dilempar ke main.py, MPU6050 adalah biang keladinya.
        self.i2c.writeto_mem(self.addr, self.REG_PWR_MGMT_1, b'\x80') 
        sleep_ms(200) # Perpanjang waktu tunggu setelah reset

        # 2. BANGUNKAN SENSOR: Mengatur register ke 0x00
        try:
            self.i2c.writeto_mem(self.addr, self.REG_PWR_MGMT_1, b'\x00')
            sleep_ms(50) 
            print(f"MPU6050 (0x{self.addr:x}): Initialized successfully.")
        except Exception as e:
            # Jika writeto_mem kedua gagal, kita konfirmasi masalahnya
            raise OSError(f"MPU6050 (0x{self.addr:x}) initialization failed during clock set: {e}")