AS       = arm-none-eabi-as
LD       = arm-none-eabi-ld
OBJCOPY  = arm-none-eabi-objcopy

TARGET   := sram_dumper
OBJECTS  := $(TARGET).o
BIN      := $(TARGET).bin

.PHONY: all clean

all: $(BIN)

$(BIN): $(TARGET).elf
	$(OBJCOPY) -O binary $< $@

$(TARGET).elf: $(OBJECTS)
	$(LD) -Ttext=0x20000000 -e _start $(OBJECTS) -o $@

$(TARGET).o: $(TARGET).S
	$(AS) -mcpu=cortex-m3 -mthumb $< -o $@

clean:
	rm -f $(TARGET).o $(TARGET).elf $(BIN)
