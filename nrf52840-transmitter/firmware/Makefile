CROSS_COMPILE ?= arm-none-eabi-
CC=$(CROSS_COMPILE)gcc
OBJCOPY=$(CROSS_COMPILE)objcopy
SIZE=$(CROSS_COMPILE)size
V?=../vendor/uf2-bootloader
T=$(V)/lib/tinyusb
N=$(V)/lib/nrfx
VERSION?=0.2.2
CFLAGS=-DFW_VERSION=\"$(VERSION)\" -mcpu=cortex-m4 -mthumb -mfloat-abi=soft -Os -g3 -fno-builtin -fno-delete-null-pointer-checks -ffunction-sections -fdata-sections -Wall -Wextra -DNRF52840_XXAA -D__STARTUP_CLEAR_BSS -D__START=main -I. -I$(N) -I$(N)/mdk -I$(N)/hal -I$(N)/drivers/include -I$(N)/drivers/src -I$(T)/src -I$(T)/hw/mcu/nordic -I$(T)/hw/mcu/nordic/cmsis/Include
SRC=stop_control.c crc32.c diagnostic.c schedule.c minilib.c main.c usb_descriptors.c $(N)/mdk/system_nrf52840.c $(N)/mdk/gcc_startup_nrf52840.S $(T)/src/tusb.c $(T)/src/common/tusb_fifo.c $(T)/src/device/usbd.c $(T)/src/device/usbd_control.c cdc_device_patched.c $(T)/src/portable/nordic/nrf5x/dcd_nrf5x.c
.PHONY: all clean FORCE
all: build/rf-test-tx.hex build/rf-test-tx.bin
build/rf-test-tx.elf: $(SRC) tusb_config.h linker.ld FORCE
	mkdir -p build
	$(CC) $(CFLAGS) $(SRC) -nostdlib -Tlinker.ld -Wl,--gc-sections,-Map=build/rf-test-tx.map -o $@
	$(SIZE) $@
build/%.hex: build/%.elf
	$(OBJCOPY) -O ihex $< $@
build/%.bin: build/%.elf
	$(OBJCOPY) -O binary $< $@
clean:
	rm -rf build
