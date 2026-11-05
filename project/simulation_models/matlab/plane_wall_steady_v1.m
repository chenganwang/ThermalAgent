function result = plane_wall_steady_v1(request)
%PLANE_WALL_STEADY_V1 Reviewed one-dimensional steady wall calculation.

required = { ...
    'thickness_m', ...
    'thermal_conductivity_w_mk', ...
    'area_m2'};
allowed = [required, {'delta_temperature_k', 'hot_temperature_c', 'cold_temperature_c'}];
if ~isstruct(request) || ~isscalar(request) || ...
        ~all(isfield(request, required)) || ~isempty(setdiff(fieldnames(request), allowed))
    error("ThermalAgent:InvalidInputs", "Input fields do not match the reviewed contract.");
end

validateattributes(request.thickness_m, {'numeric'}, {'scalar','real','finite','positive'});
validateattributes(request.thermal_conductivity_w_mk, {'numeric'}, {'scalar','real','finite','positive'});
validateattributes(request.area_m2, {'numeric'}, {'scalar','real','finite','positive'});
temperatureFields = intersect(fieldnames(request), {'delta_temperature_k', 'hot_temperature_c', 'cold_temperature_c'});
for index = 1:numel(temperatureFields)
    validateattributes(request.(temperatureFields{index}), {'numeric'}, {'scalar','real','finite'});
end
hasDelta = isfield(request, 'delta_temperature_k');
hasPair = all(isfield(request, {'hot_temperature_c', 'cold_temperature_c'}));
if ~hasDelta && ~hasPair
    error("ThermalAgent:InvalidInputs", "Provide delta_temperature_k or both hot/cold temperatures.");
end
if hasPair
    pairDifference = abs(request.hot_temperature_c - request.cold_temperature_c);
    validateattributes(pairDifference, {'numeric'}, {'scalar','real','finite','>=',0,'<=',5000});
end
if hasDelta
    temperature_difference_k = request.delta_temperature_k;
    if hasPair && abs(temperature_difference_k - pairDifference) > max(1e-9, 1e-9 * max(abs(temperature_difference_k), abs(pairDifference)))
        error("ThermalAgent:SimulationInputConflict", "Explicit temperature difference disagrees with the hot/cold pair.");
    end
else
    temperature_difference_k = pairDifference;
end
validateattributes(temperature_difference_k, {'numeric'}, {'scalar','real','finite','>=',0,'<=',5000});

heat_flux_w_m2 = request.thermal_conductivity_w_mk * temperature_difference_k / request.thickness_m;
heat_rate_w = heat_flux_w_m2 * request.area_m2;
validateattributes(heat_flux_w_m2, {'numeric'}, {'scalar','real','finite'});
validateattributes(heat_rate_w, {'numeric'}, {'scalar','real','finite'});

result = struct( ...
    'temperature_difference_k', temperature_difference_k, ...
    'heat_rate_w', heat_rate_w, ...
    'heat_flux_w_m2', heat_flux_w_m2, ...
    'formula', 'Q=k*A*delta_T/L', ...
    'model_id', 'plane_wall_steady_v1', ...
    'model_version', '1.0.0');
end
