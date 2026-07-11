# Small Tomato Systems — Hardware Cart Specification

Give this document to Web Vida GPT to turn into a locally available product cart. It describes **one small soil tomato system and one small hydroponic tomato system**, both monitored by the existing Pomona/VibeThinker-style local reasoning stack.

## Purchase assumptions

- Location/power: UAE-style **220–240 V, Type G** mains. If purchasing elsewhere, substitute the local plug/voltage version; all wet-side devices must remain 12 V or lower.
- Scale: one compact tomato plant in each system, indoors or on a sheltered, very bright balcony.
- Tomato type: choose **one dwarf or micro-dwarf determinate cherry tomato cultivar per system**. A normal indeterminate tomato will outgrow this scale.
- Aim: reliable monitoring and safe, human-approved irrigation/fertigation—not autonomous chemical dosing or unattended mains switching.
- The existing Pomona stack receives sensor events over Wi-Fi/MQTT. The small models advise; deterministic rules and the grower remain the decision makers.

## Architecture to buy

```text
Soil node: ESP32 + soil/environment sensors ─┐
                                             ├─ Wi-Fi/MQTT → Pomona gateway → guarded advice/dashboard
Hydro node: ESP32 + isolated pH/EC sensors ──┘
```

Use **one ESP32 node for each system**. It keeps the wet hydro electronics and the soil sensor wiring independent, makes calibration clearer, and lets either system keep reporting if the other is serviced.

## Shared gateway and electrical hardware — buy once

| Qty | Exact class / preferred product | Required specification | Notes for the cart builder |
|---:|---|---|---|
| 1 | Raspberry Pi 5, 8 GB **or existing always-on computer** | 64-bit Linux; wired Ethernet preferred; able to run Docker, MQTT and Pomona | Buy the Pi only if Pomona will not run continuously on an existing desktop/server. Add an official USB-C 27 W PSU, case with active cooling, 128 GB high-endurance microSD **or preferably** an SSD boot setup. |
| 2 | ESP32-S3 development board with USB-C | Wi-Fi 2.4 GHz, at least 2 I2C buses/pins accessible, 3.3 V logic | One per growing system. ESP32 is a suitable small Wi-Fi sensor controller; select a reputable board with a clear pinout, not an unbranded bare module. |
| 2 | IP65/IP66 polycarbonate electronics enclosure | Cable glands; internal mounting space; non-metallic | Mount above the highest possible spill level, outside direct sun and spray. |
| 2 | UL/CE-listed 5 V USB power supply | 220–240 V input, 2 A minimum; Type G plug | Power the ESP32 only. Keep it outside the enclosure if it runs warm. |
| 1 | Low-voltage wiring/accessory kit | Dupont/JST leads, ferrules, heat-shrink, 2-pin/3-pin waterproof connectors, cable glands, labels | Include a small breadboard/perfboard only for prototyping; make final connections strain-relieved. |
| 1 | Plug-in RCD/GFCI safety adapter or protected power strip | Local 230 V / Type G, rated for connected load | Required for hydro equipment. Keep every mains connection dry and elevated. |
| 1 | Basic climate monitor | Air temperature + RH display, min/max memory | Independent cross-check for the digital sensor. |

### Data and safety requirements

- Publish the two nodes as separate `device_id` values, sharing a `farm_id` and using distinct `zone_id` values such as `soil-pot-a` and `hydro-dwc-a`.
- Record UTC timestamps. Send temperature, humidity, pH, EC, moisture/level, and water temperature where applicable.
- Every probe needs a manual calibration/validation record. A sensor must be treated as suspect after a sudden step change, a stale reading, or calibration expiry.
- Do **not** connect a model output directly to a pump, dosing pump, valve, heater, or mains relay. Any future automation needs hard run-time limits, a manual override, leak protection, and deterministic safety checks.

## System A — small soil tomato pot

### Growing hardware

| Qty | Buy this class / search terms | Minimum specification | Why it is suitable |
|---:|---|---|---|
| 1 | Fabric grow bag with handles | **15–20 L** (4–5 US gal), breathable fabric, saucer included | Appropriate root volume for a dwarf/cherry tomato while remaining small and movable. Do not use a tiny decorative pot. |
| 1 | Heavy-duty waterproof saucer/tray | Wider than the grow bag; raised lip | Captures runoff and protects the floor. |
| 1 | Tomato-specific potting mix | Peat/coco-based, well-draining, pathogen-free; not garden soil | Consistent moisture behavior makes the sensor and Pomona advice useful. |
| 1 | Tomato cage or adjustable support stake | 90–120 cm, rust-resistant | Install at planting so roots are not damaged later. |
| 1 | Full-spectrum dimmable LED grow light with timer | Actual draw 80–120 W; white/full spectrum; hanging height adjustable | Needed unless the plant receives roughly 6–8 hours of strong direct sun. Avoid listings that only advertise misleading “equivalent watts.” |
| 1 | Clip-on oscillating fan | Low-speed setting, 220–240 V | Gentle air movement; never point a strong continuous stream at the plant. |
| 1 | Manual watering can with narrow spout | 2–5 L | Keep soil irrigation manual for v1; water based on sensor trend plus a finger/weight check. |
| 1 | Tomato fertilizer suitable for containers | Clearly labeled NPK, trace elements, instructions for edible tomatoes | Buy a single reputable product and follow its label—no automatic dosing. |

### Soil sensing node

| Qty | Preferred product / class | Required specification | Integration notes |
|---:|---|---|---|
| 1 | **DFRobot Gravity SEN0193 capacitive soil-moisture sensor** | Capacitive (not resistive); 3.3–5.5 V; analog 0–3 V | Place halfway between stem and pot edge, at root depth, not against the fabric wall. Calibrate dry and fully watered values in the actual mix. |
| 1 | ADS1115 16-bit I2C ADC module | 3.3 V-compatible I2C; 16-bit | Required because ESP32 analog input is comparatively noisy. Read the moisture probe through this module. |
| 1 | SHT31-D temperature/humidity sensor in vented protective housing | I2C, 3.3 V; sensor guard/filter cap | Mount at canopy height in shade, away from the light, fan stream, and wet soil. |
| 1 | DS18B20 waterproof temperature probe | 3.0–5.5 V, one-wire; stainless probe | Insert 5–8 cm into the root zone to separate root temperature from air temperature. |
| Optional 1 | BH1750 ambient-light sensor | I2C, 3.3 V | Useful for confirming lighting exposure and detecting a failed/timed-out grow light; mount shielded from splashes. |
| Optional 1 | 5–12 V peristaltic pump + food-safe tubing + **low-voltage** MOSFET driver | Small, self-priming; manual prime button | Buy only for a later, guarded irrigation experiment. It is not part of the first-run watering plan. |

## System B — small hydroponic tomato (DWC)

Choose a **single-plant deep-water culture (DWC) bucket**, not a multi-site countertop kit. DWC has enough root volume and nutrient stability for a dwarf tomato, while still being simple to clean and instrument.

### Growing and water hardware

| Qty | Buy this class / search terms | Minimum specification | Why it is suitable |
|---:|---|---|---|
| 1 | Opaque food-safe DWC bucket kit | **20–25 L** (5–6.5 US gal) black/opaque reservoir; matching lid; 125 mm/5 in net-pot hole | One reservoir per tomato prevents root crowding and limits light-driven algae. The reservoir must be lightproof. |
| 1 | 125 mm / 5 in net pot | Fits the lid; rigid food-safe plastic | Gives a dwarf tomato enough support. |
| 1 bag | Expanded clay pebbles (LECA) | Washed, inert hydroponic media | Rinse thoroughly before use. |
| 1 | 2-outlet aquarium air pump | 2–4 W; check valves included; suited to 20–25 L DWC | Keep pump above water level or use check valves to prevent back-siphon. |
| 2 | Large air stone | 50–100 mm; aquarium-safe | One active, one spare. |
| 1 | Airline tubing + check valves | Food/aquarium-safe silicone or PVC | Make a drip loop; replace if brittle. |
| 1 | Water-level sight tube/indicator | Opaque or shaded; compatible with bucket | Gives a fast visual check. It is preferable to relying on a cheap electronic level sensor alone. |
| 1 | Full-spectrum dimmable LED grow light with timer | Actual draw 100–150 W; hanging height adjustable | Hydro tomatoes grow quickly; use only if sunlight is inadequate. |
| 1 | Tomato hydroponic base nutrient, two-part | Specifically for hydroponic fruiting crops; A/B parts, trace elements | Buy a matched two-part product. Never pre-mix the concentrates together. |
| 1 each | pH-down and pH-up products | Hydroponic-grade; clearly labeled | Use only in small, manually measured corrections. |
| 1 | Clean food-safe mixing jug and graduated syringe/pipette set | Separate, labeled tools for nutrient A, nutrient B, pH down, and pH up | Prevents concentrate contamination and accidental overdosing. |
| 1 | Tomato support/tower + clips | 120–150 cm; stable base | DWC plants need physical support before fruiting. |

### Hydro sensing node — do not substitute bargain all-in-one probes

| Qty | Preferred product / class | Required specification | Integration notes |
|---:|---|---|---|
| 1 | **Atlas Scientific EZO-pH kit** with lab-grade/double-junction pH probe and electrically isolated carrier board | I2C or UART; 3.3–5 V; includes pH 4/7/10 calibration and storage solutions | Preferred reliable pH measurement. Keep probe wet in proper storage solution when removed—never dry or in distilled water. Electrical isolation is important around pumps. |
| 1 | **Atlas Scientific EZO-EC circuit** + K 1.0 conductivity probe + electrically isolated carrier board | I2C or UART; 3.3–5 V; includes EC calibration solution | K 1.0 covers typical hydroponic nutrient-strength measurement. Ask the retailer for the correct compatible calibration solution. |
| 1 | DS18B20 waterproof temperature probe | 3.0–5.5 V, one-wire | Suspend in the nutrient solution away from air stones; use for water temperature and pH temperature compensation. |
| 1 | Non-contact or external reservoir level sensor | Designed for opaque plastic container **or** use a protected vertical float switch | Use it as a low-level warning, not as a command to auto-fill. A float switch must be mechanically guarded from roots. |
| 1 | SHT31-D temperature/humidity sensor in vented protective housing | I2C, 3.3 V | Same canopy placement rules as the soil node. Buy a second unit rather than moving one between systems. |
| Optional 1 | Water leak sensor + 5 V alarm/buzzer | Two metal contacts; local audible alert | Place outside the reservoir on the floor/tray. It should alert, not automatically energize anything. |
| Optional 1 | BH1750 ambient-light sensor | I2C, 3.3 V | Same benefit as in the soil system. |

### Hydro operating targets to put in the dashboard (starting ranges, not automatic actions)

| Measurement | Starting target | Alert intent |
|---|---|---|
| Nutrient-solution pH | 5.8–6.2 | Flag drift; verify and correct manually in small steps. |
| EC | 1.8–2.5 mS/cm once established | Start seedlings weaker; never infer dosing from one reading. |
| Reservoir temperature | 18–22 °C preferred | Flag sustained warmth; inspect aeration and room conditions. |
| Reservoir level | Above air-stone and root-zone minimum | Low-level warning only; manually top up with correctly prepared solution. |
| Air temperature | About 20–27 °C day | Flag heat/cold stress; confirm with independent monitor. |
| Relative humidity | About 50–70% | Flag sustained high humidity/fungal-pressure conditions. |

## Calibration, consumables, and spares — essential cart items

| Qty | Item | Notes |
|---:|---|---|
| 1 set | pH 4.00, 7.00, 10.00 calibration solutions + pH probe storage solution | Buy fresh, single-use sachets or small bottles within expiry; use the pH probe maker’s specified solutions. |
| 1 set | EC calibration solution appropriate for the selected EC circuit/probe | Do not substitute a random TDS liquid without confirming its value/temperature standard. |
| 1 | Distilled/deionized water | Rinsing probes and mixing calibration solutions only; not pH-probe storage. |
| 2 | Extra capacitive soil-moisture sensors | Low-cost sensor, useful as a replacement or cross-check. |
| 1 | Spare DS18B20 and spare air stone | Simple, inexpensive failure spares. |
| 1 | Digital pH/EC handheld meter (optional but strongly recommended) | Independent verification before any manual nutrient/pH adjustment. |
| 1 | Small notebook or printable maintenance sheet | Log calibration date, probe condition, reservoir changes, and every manual adjustment. |

## What Web Vida GPT should avoid adding

- Tiny 1–5 L hydro kits, clear reservoirs, or multi-plant “smart garden” kits for the tomato plant.
- Resistive two-prong soil-moisture probes; they corrode and create bad data.
- Unbranded combined pH/EC/TDS probes without separate calibration support and known interface documentation.
- Aquarium heaters, UV sterilizers, pesticide sprayers, CO₂ systems, or automatic nutrient dosing for this first build.
- Bare mains relays, mains-powered pumps inside the electronics enclosure, or any device that makes the model able to energize equipment directly.
- Nutrient concentrates sold as one undifferentiated bottle unless the manufacturer explicitly says it is suitable for hydroponic tomatoes.

## Cart-builder handoff prompt

> Create one cart for a UAE 220–240 V / Type G customer. Include exactly the preferred hardware or a documented-compatible equivalent from this specification. Keep the soil and hydroponic ESP32 sensor nodes separate. Prioritize food-safe, opaque, corrosion-resistant, waterproof/low-voltage equipment and official datasheet availability over cheapest price. Show model numbers, connector/interface compatibility, voltage/plug type, unit price, availability, and total. Do not replace the specified isolated pH/EC measurement hardware with generic combo probes, and do not include autonomous chemical dosing or mains relay control.

## Technical references for equivalent validation

- [ESP32 official product overview](https://docs.espressif.com/projects/esp-hardware-design-guidelines/en/latest/esp32/product-overview.html) — Wi-Fi-enabled sensor-controller capability.
- [DFRobot SEN0193 documentation](https://wiki.dfrobot.com/sen0193) — capacitive soil sensor electrical range and calibration approach.
- [Atlas Scientific EZO-pH circuit](https://atlas-scientific.com/embedded-solutions/ezo-ph-circuit/) — pH circuit interface, calibration, and voltage support.
- [Atlas pH electrical-isolation guidance](https://files.atlas-scientific.com/pH_EZO_Datasheet.pdf) — isolation is strongly recommended where pumps and other sensors can introduce electrical noise.
