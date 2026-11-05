"""Independent analytic oracles; stdlib only, no production calculator imports.

These validate the stated ideal models, not manufactured systems or CFD accuracy.
The smooth turbulent correlation is Blasius; benchmark inputs avoid transition.
"""
import math

ORACLE_VERSION = "analytic-energy-darcy-fourier-v1"


def expected_values(kind, inputs):
    if kind == "none":
        return {}
    if kind == "liquid":
        mass = inputs["heat_load_w"] / inputs["specific_heat_j_kgk"] / inputs["coolant_delta_t_k"]
        volume = mass / inputs["density_kg_m3"]
        diameter = inputs["hydraulic_diameter_m"]
        velocity = volume / (math.pi * diameter ** 2 / 4)
        reynolds = inputs["density_kg_m3"] * velocity * diameter / inputs["dynamic_viscosity_pa_s"]
        if 2300 <= reynolds < 4000:
            raise ValueError("This benchmark excludes the uncertain transition regime")
        friction = 64 / reynolds if reynolds < 2300 else .3164 * reynolds ** -.25
        pressure = (friction * inputs["length_m"] / diameter + inputs["minor_loss_coefficient"]) * inputs["density_kg_m3"] * velocity ** 2 / 2
        return dict(mass_flow_kg_s=mass, volume_flow_L_min=volume * 60000, velocity_m_s=velocity,
                    reynolds_number=reynolds, pressure_drop_pa=pressure)
    if kind == "plane_wall":
        resistance = inputs["thickness_m"] / inputs["conductivity_w_mk"] / inputs["area_m2"]
        heat = inputs["delta_t_k"] / resistance
        return dict(heat_rate_W=heat, heat_flux_W_m2=heat / inputs["area_m2"], R_cond_K_per_W=resistance)
    if kind == "layered_wall":
        resistance = math.fsum(layer["thickness_m"] / layer["conductivity_w_mk"] / inputs["area_m2"] for layer in inputs["layers"])
        return dict(heat_rate=(inputs["left_temperature_k"] - inputs["right_temperature_k"]) / resistance, equivalent_resistance=resistance)
    raise ValueError("Unregistered benchmark oracle")
