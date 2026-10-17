# Hardware Setup: Radxa ZERO 3W Air-Quality Monitor

Radxa ZERO 3W (RK3566, 2 GB RAM) + PMS5003 + GY-SHT31 (SHT31-D), running DietPi.

This is the Radxa companion to the [Raspberry Pi hardware guide](HARDWARE_SETUP.md). The sensors, adapter, jumper advice, mounting and pre-power checks are the same, so this guide repeats only what differs on the Radxa and refers back for the rest. The software side of the port is tracked in [PLAN-radxa.md](../../PLAN-radxa.md).

> **The 40-pin header has the same physical layout as a Raspberry Pi, but the pin functions are different.** Do not reuse the Pi wiring. On the Radxa, pins 8 and 10 are the boot debug console, and the Pi's GPIO22/GPIO27 numbers mean nothing.

## Before You Start

> **Unplug every power source before connecting or moving a wire.** A shut-down board can still have live 5 V pins.
>
> **PMS5003 power is 5 V. GY-SHT31 power is 3.3 V. Every Radxa GPIO is 3.3 V logic (3.63 V absolute maximum) and is not 5 V tolerant.** Never join the 5 V and 3.3 V pins.

### Parts to Lay Out

| Part | What you need |
|---|---|
| Radxa ZERO 3W | 2 GB RAM model, with a 2 x 20 male header soldered on. |
| Storage | A 32 GB microSD card, ideally high-endurance or A1/A2-rated. |
| PMS5003 | Standard 8-contact model, its matching cable and a labeled breakout adapter. |
| GY-SHT31 | A breakout specified for **3.3 V operation**, with VCC/VIN, GND, SDA and SCL labeled. |
| Power supply | A regulated **5 V / 2 A or better USB-C** supply. It powers the board and both sensors. |
| Jumper connections | **8 connections** for the default build, or 9 with the optional SET wire. Keep leads short, about 10-20 cm. |
| Mounting | Nonconductive base or case, nylon standoffs and light strain relief. |
| Optional check tools | Magnifier and a multimeter for unpowered continuity checks. |

See [Using Your Male-to-Female Wires](HARDWARE_SETUP.md#using-your-male-to-female-wires) in the Pi guide for choosing jumpers or a breadboard.

## The Wiring at a Glance

Every pin number below is a **physical position** on the 40-pin header. Pin 1 is the square pad, and odd pins run along the same row as pin 1.

```
                 Radxa ZERO 3W 40-pin header (used pins marked)

   SHT31 VIN  W5 -> [ 1] 3.3V          5V   [ 2] <- W1 PMS VCC
   SHT31 SDA  W7 -> [ 3] I2C3_SDA       5V   [ 4]
   SHT31 SCL  W8 -> [ 5] I2C3_SCL       GND  [ 6] <- W2 PMS GND
                    [ 7]                DBG  [ 8]    debug console TX - DO NOT USE
   SHT31 GND  W6 -> [ 9] GND            DBG  [10]    debug console RX - DO NOT USE
                    [11]                     [12]
                    [13]                GND  [14]
   PMS SET (opt) W9 [15] GPIO3_B0  UART4_RX  [16] <- W3 PMS TX
                    [17] 3.3V      UART4_TX  [18] <- W4 PMS RX
                    [19]                GND  [20]
                       ...  pins 21-40 unused ...
```

Colors are suggestions; label both ends W1-W9 if yours differ.

### PMS5003 Through Its Labeled Adapter

| Wire | Suggested color | Sensor-side label | PMS5003 native contact | Radxa pin | Radxa signal |
|---|---|---|---|---|---|
| W1 | Red | VCC / 5V | 1 | 2 | +5 V |
| W2 | Black | GND | 2 | 6 | Ground |
| W3 | Blue | TX / TXD | 5 | 16 | UART4_RX_M1 (GPIO3_B1), receives sensor data |
| W4 | White | RX / RXD | 4 | 18 | UART4_TX_M1 (GPIO3_B2), sends commands to the sensor |
| W9 | Green | SET / EN (optional) | 3 | 15 | GPIO3_B0, sleep/wake line |
| — | — | RESET / RST | 6 | NC | Leave unconnected |

**W4 is required on the Radxa, unlike the Pi build.** With SET unwired, the reader puts the sensor to sleep and wakes it with UART commands. Those commands travel over W4. Without W4 the fan runs constantly, which shortens the sensor's life.

**SET and RESET are not wired by default.** The PMS5003 has internal pull-ups, so floating SET means "awake" and floating RESET means "running". UART sleep/wake works without them. If you fit W9, drive it through libgpiod: run `uv sync --extra radxa`, confirm the line with `gpioinfo` (pin 15 is expected to be `gpiochip3` line 8), then set `pin_enable = "gpiochip3:8"` in `config.toml`. Never tie SET or RESET directly to a supply.

Leave native PMS5003 contacts 7 and 8 unconnected. Read your adapter's labels rather than its pin order, as described in the [Pi guide](HARDWARE_SETUP.md#pms5003-through-its-labeled-adapter).

### GY-SHT31

| Wire | Suggested color | Sensor-side label | Radxa pin | Radxa signal |
|---|---|---|---|---|
| W5 | Orange | VCC / VIN | 1 | +3.3 V |
| W6 | Black | GND | 9 | Ground |
| W7 | Yellow | SDA | 3 | I2C3_SDA_M0 (GPIO1_A0) |
| W8 | Purple | SCL | 5 | I2C3_SCL_M0 (GPIO1_A1) |

SDA goes to SDA and SCL to SCL; they do not cross. The Radxa already has I2C pull-ups on pins 3 and 5, so no extra resistors are needed with short leads.

Power the GY-SHT31 from 3.3 V only. A breakout fed from 5 V usually pulls SDA/SCL up to 5 V, which can damage the RK3566. Leave its address jumper at the default **0x44**.

### Pins to Avoid

| Pins | Why |
|---|---|
| 8, 10 | UART2_M0 is the U-Boot and kernel debug console at 1,500,000 baud. Sensor data arriving here can stop the board from booting. |
| 26 | Not connected on the ZERO 3W. |
| 27, 28 | Have extra I2C pull-ups. Fine for a second I2C sensor, but unsuitable as plain GPIO. |

## Step-by-Step Assembly

Steps 1, 3, 4 and 8 of the [Pi guide](HARDWARE_SETUP.md#step-by-step-assembly) apply unchanged: make the work area safe, prepare reliable connections, seat the PMS cable, and mount the parts. The Radxa-specific steps are below.

### 1. Orient the Board and Find Pin 1

Hold the board component side up, with the 40-pin header along the top edge. Pin 1 has a square solder pad, and is at the end of the header nearest the board's corner marking. Check against the silkscreen and Radxa's [hardware interface page](https://docs.radxa.com/en/zero/zero3/hardware-design/hardware-interface) before connecting anything.

### 2. Connect PMS5003 Power and Data

Connect one wire at a time:

1. **W2:** adapter **GND** to pin **6**.
2. **W1:** adapter **VCC/5V** to pin **2**.
3. **W3:** adapter **TX/TXD** to pin **16**.
4. **W4:** adapter **RX/RXD** to pin **18**.

The sensor's TX goes to the board's RX, and the sensor's RX to the board's TX. The PMS5003 needs 5 V for its fan, but its serial signals are 3.3 V, so no level shifter is needed.

### 3. Optional: Connect SET

**W9:** adapter **SET** to pin **15**. Skip this for the default build.

### 4. Connect the GY-SHT31

1. **W6:** **GND** to pin **9**.
2. **W5:** **VCC/VIN** to pin **1** (3.3 V).
3. **W7:** **SDA** to pin **3**.
4. **W8:** **SCL** to pin **5**.

### 5. Mount With Heat in Mind

The RK3566 runs warmer than a Pi Zero 2 W. Mount the GY-SHT31 at least 5 cm from the board, on the side away from the SoC, power supply and PMS exhaust. A short cable that holds the SHT31 outside the case gives the most accurate temperature and humidity. Keep the PMS inlet and outlet clear, as in the Pi guide.

Do not enclose the board in a metal box, which blocks Wi-Fi.

### 6. Inspect Before Power

- [ ] All power is disconnected.
- [ ] PMS5003 VCC goes only to **pin 2 / 5 V**.
- [ ] GY-SHT31 VCC/VIN goes only to **pin 1 / 3.3 V**.
- [ ] PMS GND goes to pin 6; SHT31 GND goes to pin 9.
- [ ] PMS TX goes to pin **16**; PMS RX goes to pin **18**.
- [ ] Nothing is connected to pins 8 or 10.
- [ ] RESET is unconnected; SET is unconnected or on pin 15.
- [ ] SHT31 SDA goes to pin 3 and SCL to pin 5.
- [ ] Every connector sits on exactly one intended pin, not shifted by a row.
- [ ] Sensor openings are clear, and the metal PMS case cannot touch any contact.

### 7. Power Up

Power the board through **USB-C 1**, the port marked for power and OTG. The other USB-C port is a USB 3.0 host and does not power the board. Do not power the sensors separately or feed power into the header.

The PMS fan should start within a few seconds. A spinning fan only shows that the sensor has power, not that data reaches the board.

## Enable the UART and I2C in DietPi

DietPi loads device-tree overlays from `/boot/dietpiEnv.txt`. Overlay names vary between images, so check the real filenames first:

```sh
ls /boot/dtb/rockchip/overlay/ | grep -Ei 'uart4|i2c3'
```

Then edit `/boot/dietpiEnv.txt` to match. The expected shape is:

```
overlay_path=rockchip
overlay_prefix=rk3568
overlays=uart4-m1 i2c3-m0
```

If the files are named `radxa-zero3-...`, use `overlay_prefix=radxa-zero3` instead. Reboot after editing. DietPi issue [MichaIng/DietPi#7573](https://github.com/MichaIng/DietPi/issues/7573) reports overlay-prefix problems on this board; if no new devices appear, try the other prefix.

## Verify the Wiring

Install the tools once:

```sh
sudo apt install -y i2c-tools xxd
```

| Check | Command | Expected result |
|---|---|---|
| Devices exist | `ls /dev/ttyS4 /dev/i2c-3` | Both paths are listed. |
| No login console on the UART | `systemctl status serial-getty@ttyS4` | Inactive or not found. |
| PMS5003 data | `stty -F /dev/ttyS4 9600 raw; timeout 5 xxd /dev/ttyS4 \| head` | Lines containing `424d`, the frame header. |
| SHT31 present | `sudo i2cdetect -y 3` | `44` in the grid. |

## Configure the Monitor

Set these values in `config.toml`:

```toml
[sensor]
device = "/dev/ttyS4"
pin_enable = -1   # SET not driven; the reader uses UART sleep/wake commands
pin_reset = -1    # RESET not wired
i2c_bus = 3       # SHT31 on /dev/i2c-3
```

`deploy/install.sh` detects the Radxa and writes these values (plus `commit_interval_s = 300`) into a fresh `/etc/pm25/config.toml`. `pm25-setup` also asks for the I2C bus.

## Troubleshooting

| Symptom | Likely cause and fix |
|---|---|
| `/dev/ttyS4` or `/dev/i2c-3` missing | Overlay not loaded. Check the names and prefix in `/boot/dietpiEnv.txt`, then reboot. Run `dmesg \| grep -i overlay`. |
| No `424d` bytes | TX/RX swapped, the adapter's TX/RX labels are board-relative, or the fan has no 5 V. Swap W3 and W4 with power off. |
| Fan never stops between readings | W4 is missing or on the wrong pin, so sleep commands never arrive. |
| Board will not boot, or stops at a U-Boot prompt | Something is wired to pin 8 or 10. Power off and move it. |
| `i2cdetect` shows nothing | SDA/SCL swapped, the sensor is on 5 V, or it is on the wrong bus. Try `i2cdetect -l` to list buses. |
| `i2cdetect` shows `45` | The address jumper is set. Use `0x45` in config, or restore the jumper. |
| Temperature reads several degrees high | The SHT31 is too close to the SoC or the PMS exhaust. Move it out of the case. |
| Readings stop after a few days | Check the supply and cable; a weak 5 V supply browns out when the PMS fan and Wi-Fi peak together. |

### Alternative Pins

Use these only if the default pins are taken. Each needs its own overlay.

| Function | Pins | Linux node |
|---|---|---|
| UART9_M1 | 21 TX, 24 RX | `/dev/ttyS9` |
| UART5_M1 | 32 TX, 33 RX | `/dev/ttyS5` |
| I2C4_M0 | 27 SDA, 28 SCL | `/dev/i2c-4` |
| I2C5_M0 | 31 SDA, 29 SCL | `/dev/i2c-5` |

## Reference

- [Radxa ZERO 3 hardware interface](https://docs.radxa.com/en/zero/zero3/hardware-design/hardware-interface): 40-pin functions, 3.3 V GPIO limit, debug console on pins 8/10, I2C pull-ups on pins 3/5/27/28, USB-C 1 power at 5 V / 2 A.
- [Plantower PMS5003 manual, version 2.3](https://cdn-shop.adafruit.com/product-files/3686/plantower-pms5003-manual_v2-3.pdf): connector pinout, 5 V supply, 3.3 V logic, internal SET/RESET pull-ups and UART sleep/wake commands.
- [Adafruit SHT31-D pin reference](https://learn.adafruit.com/adafruit-sht31-d-temperature-and-humidity-sensor-breakout/pinouts): I2C roles and supply/pull-up voltage.

These instructions were checked against the documentation and this repository's code. They have **not been tested on physical Radxa hardware**, and the overlay names in particular must be confirmed on your DietPi image.
