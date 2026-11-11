ENTRY(Reset_Handler)
MEMORY { FLASH(rx) : ORIGIN = 0x23000, LENGTH = 0x1d000
RAM(rwx) : ORIGIN = 0x20000000, LENGTH = 256K }
SECTIONS {
.text : { KEEP(*(.isr_vector)) KEEP(*(.recovery_contract)) *(.text*) *(.rodata*) . = ALIGN(4); } > FLASH
.ARM.exidx : { *(.ARM.exidx*) } > FLASH
. = ALIGN(4); __etext = .;
.data : AT(__etext) { __data_start__ = .; *(.data*) . = ALIGN(4); __data_end__ = .; } > RAM
.bss (NOLOAD) : { __bss_start__ = .; *(.bss*) *(COMMON) . = ALIGN(4); __bss_end__ = .; } > RAM
.stack (NOLOAD) : { . = ALIGN(8); __StackLimit = .; . += 8192; __StackTop = .; } > RAM
__flash_end = __etext + SIZEOF(.data);
ASSERT(__flash_end <= 0x40000, "Application crosses approved flash limit")
/DISCARD/ : { *(.stack*) *(.heap*) *(.comment*) *(.note*) }
}
