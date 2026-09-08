"""Independent real hardware lifecycle; unavailable hardware is never simulated."""
from __future__ import annotations

import math
import warnings
from dataclasses import dataclass

import config


class HardwareUnavailable(ValueError):
    code = "hardware_unavailable"

    def __init__(self, component, reason):
        self.component = component
        super().__init__(f"{component} unavailable: {reason}")


def describe_error(exc):
    return f"{type(exc).__name__}: {exc}"[:300]


def cleanup_gpio(gpio, pins=None):
    # GPIO setup may have failed before claiming any pins. Only suppress that
    # harmless cleanup warning; setup failures and cleanup exceptions stay visible.
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="No channels have been set up yet.*", category=RuntimeWarning)
        if pins is None:
            gpio.cleanup()
        else:
            gpio.cleanup(pins)


def real_motors():
    from hardware.motors import MotorController, MotorPins, GPIO
    if GPIO is None:
        raise RuntimeError("Install rpi-lgpio in the Pi environment")
    pins = config.PINS["motor"]
    motor = MotorController(MotorPins(**pins), default_speed=config.DEFAULT_SPEED)
    try:
        if motor._pwm_left is None or motor._pwm_right is None:
            raise RuntimeError("Motor GPIO/PWM initialization failed; check Pi 5 rpi-lgpio installation")
        if any(GPIO.gpio_function(pin) != GPIO.OUT for pin in pins.values()):
            raise RuntimeError("Motor pins were not configured as outputs")
        motor.drive(0, 0, 0)
        return motor
    except Exception:
        # A partially initialized PWM must not keep running. Do not call global
        # GPIO.cleanup here: another component may already own healthy pins.
        for pwm in (motor._pwm_left, motor._pwm_right):
            if pwm is not None:
                try:
                    pwm.stop()
                except Exception:
                    pass
        try:
            cleanup_gpio(GPIO, list(pins.values()))
        except Exception:
            pass
        raise


def real_servos():
    from hardware.servos import PanTilt, ServoConfig
    servo = PanTilt(ServoConfig(**config.PINS["servo"]))
    if servo._pca is None or not hasattr(servo, "pan") or not hasattr(servo, "tilt"):
        raise RuntimeError("PCA9685 unavailable; check ServoKit, I2C and the connected servo board")
    try:
        servo.center()
        return servo
    except Exception:
        try:
            servo._pca._pca.deinit()
        except Exception:
            pass
        raise


def real_pump():
    from hardware.relay_led import RelayLED, GPIO
    if GPIO is None:
        raise RuntimeError("Install rpi-lgpio in the Pi environment")
    pins = config.PINS["sensors"]
    relay = RelayLED(pins["relay"], pins.get("led"))
    if GPIO.gpio_function(pins["relay"]) != GPIO.OUT:
        raise RuntimeError("Pump relay GPIO initialization failed")
    relay.pump_off()
    return relay


def real_sensor(group, index):
    from hardware.sensors import Sensors, SensorPins
    channels = {"flame_array": [], "ir_array": []}
    channels[group] = [config.PINS["sensors"][group][index]]
    sensor = Sensors(SensorPins(**channels))
    if not sensor._setup_ok:
        raise RuntimeError("Sensor GPIO initialization failed; check rpi-lgpio")
    return sensor


@dataclass
class Component:
    state: str = "disabled"
    reason: str | None = "Disabled in configuration"
    device: object = None

    @property
    def available(self):
        return self.state in ("available", "simulated")

    def fail(self, exc):
        self.state, self.reason = "unavailable", describe_error(exc)

    def status(self):
        return {"state": self.state, "available": self.available, "reason": self.reason}


class SensorBank:
    """Independent inputs with observed signal evidence, not attachment guesses."""
    def __init__(self, factory, flame_channels, ir_channels):
        self.channels = {group: [Component() for _ in range(4)] for group in ("flame_array", "ir_array")}
        self.observations = {group: [{"value": -1, "samples": 0, "changes": 0, "read_errors": 0,
                                     "last_valid": None} for _ in channels]
                             for group, channels in self.channels.items()}
        for group, indices in (("flame_array", flame_channels), ("ir_array", ir_channels)):
            for index in indices:
                component = self.channels[group][index]
                try:
                    component.device = factory(group, index)
                    component.state, component.reason = "available", None
                except Exception as exc:
                    component.fail(exc)

    def read(self):
        result = {group: [-1] * 4 for group in self.channels}
        for group, components in self.channels.items():
            for index, component in enumerate(components):
                observation = self.observations[group][index]
                observation["value"] = -1
                # Retry read faults on the next sample. Setup failures need a restart
                # after fixing the driver/OS setup; they have no device to read.
                if component.device is not None:
                    try:
                        value = component.device.read()[group][0]
                        if type(value) is not int or value not in (0, 1):
                            raise ValueError("No valid digital reading; check the channel")
                        result[group][index] = value
                        if observation["last_valid"] is not None and observation["last_valid"] != value:
                            observation["changes"] += 1
                        observation["value"] = observation["last_valid"] = value
                        observation["samples"] += 1
                        component.state, component.reason = "available", None
                    except Exception as exc:
                        observation["read_errors"] += 1
                        component.fail(exc)
        return result

    def status(self):
        selected = [c for group in self.channels.values() for c in group if c.state != "disabled"]
        count = sum(c.available for c in selected)
        state = ("disabled" if not selected else "available" if count == len(selected)
                 else "partial" if count else "unavailable")
        channels = {}
        for group, values in self.channels.items():
            channels[group] = []
            for index, component in enumerate(values):
                observation = self.observations[group][index]
                evidence = ("no_valid_reading" if not observation["samples"] else
                            "signal_changed" if observation["changes"] else "steady_signal")
                channels[group].append({**component.status(), "gpio": config.PINS["sensors"][group][index],
                                       **{key: value for key, value in observation.items() if key != "last_valid"},
                                       "evidence": evidence})
        return {"state": state, "available": bool(count), "configured_channels": len(selected),
                "readable_channels": count, "presence": "GPIO_only_not_sensor_detection",
                "channels": channels}


class HardwareComponents:
    def __init__(self, *, simulation=False, factories=None, enabled=None, flame_channels=None, ir_channels=None):
        self.simulation = simulation
        self.parts = {name: Component() for name in ("motors", "servos", "pump")}
        self.cleanup_errors = []
        if simulation:
            from simulation import SimMotors, SimServos, SimRelay, SimSensors
            for name, factory in (("motors", SimMotors), ("servos", SimServos), ("pump", SimRelay)):
                self.parts[name] = Component("simulated", None, factory())
            self.sensors = SimSensors()
            return
        factories = factories if factories is not None else {
            "motors": real_motors, "servos": real_servos, "pump": real_pump, "sensor": real_sensor}
        enabled = enabled if enabled is not None else {
            "motors": config.MOTORS_ENABLED, "servos": config.SERVOS_ENABLED, "pump": config.PUMP_ENABLED}
        for name, component in self.parts.items():
            if enabled.get(name, True):
                try:
                    component.device = factories[name]()
                    component.state, component.reason = "available", None
                except Exception as exc:
                    component.fail(exc)
            print(f"Hardware {name}: {component.state}" + (f" ({component.reason})" if component.reason else ""))
        flame = config.FLAME_CHANNELS if flame_channels is None else flame_channels
        ir = config.IR_CHANNELS if ir_channels is None else ir_channels
        self.sensors = SensorBank(factories["sensor"], flame if config.ENABLE_SENSORS else (), ir if config.ENABLE_SENSORS else ())
        sensors = self.sensors.status()
        print(f"Hardware sensors: {sensors['state']} ({sensors['readable_channels']}/{sensors['configured_channels']} GPIO inputs initialized; trigger sensors to verify them)")

    def require(self, name):
        component = self.parts[name]
        if not component.available:
            raise HardwareUnavailable(name, component.reason or component.state)
        return component.device

    def call(self, name, operation, *args):
        device = self.require(name)
        try:
            return getattr(device, operation)(*args)
        except Exception as exc:
            self.parts[name].fail(exc)
            # Best-effort off for the failing output; never fabricate success.
            if name in ("motors", "pump"):
                try:
                    getattr(device, "stop" if name == "motors" else "pump_off")()
                except Exception:
                    pass
            raise HardwareUnavailable(name, self.parts[name].reason) from exc

    def servo_angles(self):
        component = self.parts["servos"]
        if not component.available:
            return {"pan": None, "tilt": None}
        try:
            angles = {axis: getattr(component.device, axis).angle for axis in ("pan", "tilt")}
            if any(type(value) not in (int, float) or not 0 <= value <= 180 or not math.isfinite(value) for value in angles.values()):
                raise ValueError("Invalid servo angle readback")
            return angles
        except Exception as exc:
            component.fail(exc)
            return {"pan": None, "tilt": None}

    def move_servos(self, pan, tilt):
        self.require("servos")
        before = self.servo_angles()
        self.require("servos")
        expected = {axis: max(0, min(180, before[axis] + (delta or 0))) for axis, delta in (("pan", pan), ("tilt", tilt))}
        self.call("servos", "set_pan_tilt", pan, tilt)
        after = self.servo_angles()
        # The existing driver logs some write failures instead of raising.
        # Check commanded-angle readback so those failures reach the caller.
        if any(after[axis] is None or abs(after[axis] - expected[axis]) > 1 for axis in expected):
            self.parts["servos"].fail(RuntimeError("Servo write/readback failed; position is unknown"))
            raise HardwareUnavailable("servos", self.parts["servos"].reason)

    def pump_state(self):
        if not self.parts["pump"].available:
            return None
        try:
            value = self.call("pump", "state")
            if type(value) is not bool:
                raise ValueError("Invalid pump state")
            return value
        except Exception as exc:
            self.parts["pump"].fail(exc)
            return None

    def status(self):
        result = {name: part.status() for name, part in self.parts.items()}
        for name in ("motors", "pump"):
            result[name]["presence"] = "simulated" if self.simulation else "GPIO_only_not_load_detection"
        result["servos"]["presence"] = "simulated" if self.simulation else "controller_only_not_physical_position"
        result["sensors"] = ({"state": "simulated", "available": True, "presence": "simulated"}
                             if self.simulation else self.sensors.status())
        return result

    def close(self):
        # Only final process cleanup may release all GPIO pins. Drivers retain
        # their objects after a fault so partially working resources can close.
        for name, component in self.parts.items():
            device = component.device
            if device is None:
                continue
            try:
                if name == "pump":
                    device.led(False)
                elif name == "servos" and not self.simulation:
                    device._pca._pca.deinit()
            except Exception as exc:
                self.cleanup_errors.append(f"{name}: {describe_error(exc)}")
        motor = self.parts["motors"].device
        try:
            if motor is not None:
                motor.shutdown()
        except Exception as exc:
            self.cleanup_errors.append(f"motors: {describe_error(exc)}")
        if not self.simulation:
            # Sensors/pump can own GPIO even when motors never initialized.
            import sys
            gpio = sys.modules.get("RPi.GPIO")
            if gpio is not None:
                try:
                    cleanup_gpio(gpio)
                except Exception as exc:
                    self.cleanup_errors.append(f"GPIO: {describe_error(exc)}")
