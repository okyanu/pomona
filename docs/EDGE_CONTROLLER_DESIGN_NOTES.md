# Pomona Edge Controller Design Notes

**Status:** exploratory / pre-implementation
**Related phase:** Phase 8 — ESP32 devices
**Current platform priority:** Phase 2 — dashboard and persistence

## Purpose

This document captures early design principles for Pomona's future physical
edge-device layer.

Pomona is an offline-first, modular, safety-constrained agriculture platform.
The hardware layer should extend the existing sensor ingestion, reasoner,
automation, and deterministic safety architecture without allowing models or
LLMs to directly control physical actuators.

These notes are informed by community discussions around DIY hydroponic
controllers, greenhouse automation, sensor redundancy, irrigation safety, and
open-source controller designs.

Nothing described here represents an adopted hardware design yet.

## Design goals

The future Pomona edge hardware should:

- operate locally without requiring cloud connectivity;
- use inexpensive and widely available microcontrollers such as ESP32;
- expose open, documented sensor and actuator interfaces;
- communicate with Pomona Core through a simple local protocol such as MQTT;
- tolerate network loss, process crashes, and device reboots;
- fail to a safe physical state;
- separate sensing, decision-making, and actuation;
- make hardware faults observable by the software platform;
- support manual maintenance and emergency operation;
- remain modular rather than require one large all-purpose controller PCB.

Pomona should not depend on a specific hydroponic system topology.
The same contracts should eventually support hydroponic, greenhouse,
irrigation, aquaponic, and other controlled-agriculture deployments.

## Proposed architecture

A possible architecture is:

```text
                         Pomona Core
                 Raspberry Pi / PC / Mac
                            │
                           MQTT
                            │
               ┌────────────┴────────────┐
               │                         │
        Sensor Node                 Actuator Node
           ESP32                       MCU
               │                         │
     ┌─────────┼─────────┐       ┌──────┼──────┐
     │         │         │       │      │      │
    pH        EC       Temp     Pump   Valve  Aeration
     │                   │
   Level               Flow
```

Sensor and actuator responsibilities should remain logically separate even
when early prototypes use a single ESP32.

This separation allows future systems to distribute devices across multiple
physical zones without changing the Pomona Core architecture.

## Hardware safety boundary

Pomona's deterministic safety layer remains the final software authority.
However, software safety alone is not sufficient.
Critical physical protections should exist below the application layer.

The desired hierarchy is:

```text
Model / LLM
    │
    ▼
Reasoner
    │
    ▼
Automation suggestion
    │
    ▼
Deterministic safety checker
    │
    ▼
Actuator command gate
    │
    ▼
Device firmware validation
    │
    ▼
Hardware interlock
    │
    ▼
Physical actuator
```

A failure in a higher layer must not bypass protections in a lower layer.

## Operating modes

Future Pomona hardware should expose explicit operating states.

Example:

```text
AUTOMATIC
MANUAL
MAINTENANCE
EMERGENCY_STOP
FAULT
```

Suggested semantics:

**AUTOMATIC**
Normal Pomona operation.
Commands may be accepted only after deterministic safety validation.

**MANUAL**
Human-controlled operation.
Safety limits still apply.

**MAINTENANCE**
Automation is suspended while hardware is being inspected, cleaned,
calibrated, or serviced.

**EMERGENCY_STOP**
Physical actuator power is disabled.
Software must never be able to override this state.

**FAULT**
The device has detected a condition that prevents safe automatic operation.

## Physical emergency stop

A future reference controller should consider a physical, latching emergency
stop.

The E-stop should disable actuator power independently of:

- Pomona Core;
- MQTT;
- the ESP32 application;
- reasoner output;
- automation rules.

Example:

```text
Pomona Core
     │
    OFF
     │

ESP32
     │
    OFF
     │

E-STOP ──────── physically disables actuator power
```

Software may observe the E-stop state but must not be capable of clearing it.

## Sensor priorities

Sensor selection should prioritize failure detection rather than simply
maximizing the number of measurements.

### Tier 1 — core sensors

Initial reference hardware should investigate:

```text
water_temperature
water_level
low_water_switch
flow_rate
ph
ec
```

These provide the minimum useful picture for hydroponic and irrigation
monitoring.

### Tier 2 — reliability sensors

Potential additional sensors:

```text
reservoir_mass
pump_current
ambient_temperature
ambient_humidity
```

These measurements are particularly useful because they can reveal system
failures rather than only environmental conditions.

### Tier 3 — specialized sensing

Future deployments may optionally support:

```text
dissolved_oxygen
orp
additional_water_chemistry
light / PAR
substrate sensors
```

These should not become requirements for the base Pomona hardware contract.

## Redundant sensing

Pomona should support redundant sensors when the redundancy provides useful
failure detection.

For example:

```text
continuous_level_sensor
+
low_level_float_switch
```

The continuous sensor is useful for telemetry and trends.
The float switch can provide a simple independent safety signal.

Example:

```text
reported_level = 52%
low_level_switch = ACTIVE
```

should not be silently accepted.
It should produce something similar to:

```text
SENSOR_CONFLICT
```

This data can feed both deterministic validation and Pomona's sensor-quality
reasoning layer.

## Flow-based failure detection

Flow measurement is particularly valuable for irrigation systems.

Combining:

```text
pump_command
valve_command
flow_rate
reservoir_level
```

allows several failures to be detected deterministically.

Example:

```text
pump_command = ON
flow_rate = 0
```

Possible interpretation:

```text
BLOCKAGE
PUMP_FAILURE
EMPTY_RESERVOIR
SENSOR_FAILURE
```

Another example:

```text
pump_command = OFF
flow_rate > threshold
```

Possible interpretation:

```text
STUCK_VALVE
SIPHONING
LEAK
FLOW_SENSOR_FAULT
```

These conditions should normally be identified by deterministic rules before
any AI reasoning is considered.

## Reservoir mass monitoring

A load cell under the reservoir is worth evaluating as an optional sensor.

Reservoir mass over time can provide:

- water consumption estimates;
- leak detection;
- unexpected water-loss detection;
- refill verification;
- additional digital-twin observations.

Example:

```text
expected_loss:
1.8 L/day

observed_loss:
7.2 L/hour
```

could immediately generate a critical water-loss condition.

This may eventually provide useful input for digital-twin and irrigation-risk
models.

## Sensor quality

The edge-device contract should expose enough metadata for Pomona to
distinguish a biological event from a sensor problem.

Sensor packets should eventually support information such as:

```text
device_id
sensor_id
measurement
unit
timestamp
sequence
status
calibration_timestamp
```

Possible quality states:

```text
VALID
MISSING
STALE
SUSPECT
CONFLICTING
DISCONNECTED
```

Sensor-quality classification should complement deterministic sanity checks,
not replace them.

## Device communication

MQTT is the preferred initial transport because Pomona already uses MQTT
internally.

Possible telemetry structure:

```text
pomona/device/<device_id>/telemetry
pomona/device/<device_id>/status
pomona/device/<device_id>/fault
pomona/device/<device_id>/ack
```

Potential command path:

```text
pomona/device/<device_id>/command
```

Commands should use a strict allowlisted schema.

Example:

```json
{
  "command_id": "abc123",
  "actuator": "irrigation_pump_1",
  "action": "ON",
  "max_duration_seconds": 20
}
```

Arbitrary code or arbitrary natural-language commands must never reach
device firmware.

## Command acknowledgement

Actuator commands should eventually have explicit acknowledgements.

Example:

```text
REQUESTED
ACCEPTED
EXECUTING
COMPLETED
REJECTED
FAULT
```

The platform must not assume:

```text
command sent == physical action completed
```

Device state must be observable independently.

## Local device protections

Possible firmware-level protections include:

```text
watchdog
command timeout
maximum actuator runtime
stale-command rejection
low-water blocking
duplicate-command protection
boot-safe actuator state
network-loss recovery
```

Outputs should default to a safe state during reboot.
For irrigation equipment, this generally means:

```text
pump = OFF
valve = CLOSED
```

unless a particular validated hardware design requires otherwise.

## Hardware interlocks

Some protections should exist independently from firmware.

Examples:

```text
LOW WATER
    │
    └── hardware interlock ──> pump disabled
```

or:

```text
E-STOP
    │
    └── actuator supply disabled
```

This means a software crash, stuck process, or compromised network connection
does not automatically create an unsafe physical state.

## Failure scenarios to test

Any Pomona reference controller should eventually have a bench-validation
matrix.

At minimum:

```text
ESP32 reboot
Pomona Core crash
MQTT disconnect
Wi-Fi disconnect
sensor disconnect
stale sensor data
contradictory sensors
pump running with zero flow
unexpected flow while pump is off
reservoir loss
stuck relay
power interruption
device restart
emergency stop
maintenance mode
```

The expected behavior for every failure should be documented before field
deployment.

## Chemical dosing boundary

Automatic nutrient, fertilizer, pesticide, pH-adjustment, or other chemical
dosing is intentionally outside the current Pomona actuator scope.

Pomona reasoners may produce advisory information such as:

```text
EC is below the expected range.

Possible action:
Review nutrient concentration.

Human review required.
```

They must not directly produce commands such as:

```text
run nutrient pump for 7 seconds
```

Chemical recommendations and physical chemical dosing are separate safety
domains.

This restriction remains in place even if external controller designs include
peristaltic dosing pumps.

## AI boundary

Models may help with:

```text
sensor-quality classification
tomato risk
water / irrigation risk
nutrient / pH-EC interpretation
daily summaries
digital-twin scenarios
```

Models must not bypass:

```text
deterministic rules
command allowlists
device safety constraints
human approval
hardware interlocks
```

The desired rule remains:

> AI can advise. Deterministic systems decide whether a physical command is
> allowed.

## Reference hardware strategy

Pomona should not immediately attempt to design one monolithic controller PCB.

A better progression is:

```text
1. Hardware contracts
2. ESP32 sensor prototype
3. MQTT telemetry
4. Fault simulation
5. Read-only physical deployment
6. Irrigation actuator prototype
7. Deterministic safety tests
8. Hardware interlocks
9. Reference PCB
```

This keeps hardware development aligned with the existing software platform
instead of forcing the software architecture around an early PCB design.

## External collaboration

DIY hydroponic controller projects are useful potential collaboration points,
especially when they explore:

- open-source PCB design;
- ESP32 sensor interfaces;
- electrical isolation;
- relay and MOSFET design;
- physical emergency stops;
- maintenance modes;
- irrigation flow sensing;
- redundant water-level sensing;
- pump failure detection;
- modular sensor/actuator nodes.

Before integrating an external hardware project, Pomona should evaluate:

```text
license
schematics availability
firmware availability
component availability
electrical safety
isolation
failure behavior
MQTT compatibility
device identity
command acknowledgement
maintenance status
```

External projects should initially be treated as design references or
collaboration opportunities rather than assumed dependencies.

## Proposed Phase 8 decomposition

The current roadmap lists Phase 8 as ESP32 devices.

A future implementation could divide it into:

### Phase 8.1 — Sensor node contract

Define:

```text
telemetry schema
device identity
sensor identity
timestamps
quality metadata
MQTT topics
device health
```

### Phase 8.2 — ESP32 sensor reference

Initial read-only hardware supporting a limited sensor set.
No actuator control required.

### Phase 8.3 — Hardware safety contract

Define:

```text
maintenance mode
E-stop
watchdog
default-safe outputs
low-water interlock
command timeout
```

### Phase 8.4 — Irrigation actuator node

Support only explicitly allowlisted irrigation actuators.

### Phase 8.5 — Failure detection

Implement deterministic handling for:

```text
no-flow
unexpected-flow
sensor disagreement
stale telemetry
reservoir loss
device disconnect
```

### Phase 8.6 — Bench validation

Test physical and software failure scenarios before any broader deployment.

## Current decision

No external hydroponic controller has been adopted by Pomona.
No PCB design has been selected.
No external controller should currently be described as a Pomona integration.

Community controller projects are being studied to improve the future Phase 8
hardware contract and identify potential open-source collaborators.

The immediate Pomona priority remains the existing software roadmap.
Hardware development should begin only when the platform contracts are stable
enough that hardware can implement them rather than define them.
