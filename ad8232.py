# ad8232.py
from machine import Pin, ADC

class AD8232:
    """Driver untuk sensor EKG AD8232 (Analog)."""

    def __init__(self, adc_pin):
        """Inisialisasi pin ADC untuk pembacaan sinyal jantung."""
        self.adc_pin = adc_pin
        self.adc = ADC(Pin(adc_pin))
        
        # Atur resolusi dan attenuasi (sesuai yang Anda pakai)
        self.adc.width(ADC.WIDTH_12BIT)
        self.adc.atten(ADC.ATTN_11DB)
        
        print(f"AD8232: Initialized on ADC Pin {adc_pin}.")

    def read_ekg(self):
        """Membaca nilai mentah sinyal EKG (0-4095)."""
        return self.adc.read()