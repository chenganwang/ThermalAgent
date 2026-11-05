function response_json = thermalagent_dispatch(model_id, request_json)
%THERMALAGENT_DISPATCH Controlled entry point for reviewed ThermalAgent models.
%   This dispatcher intentionally exposes only a fixed switch. It never
%   evaluates user-provided function names, commands, or filesystem paths.

arguments
    model_id (1,1) string
    request_json (1,1) string
end

request = jsondecode(request_json);

switch model_id
    case "plane_wall_steady_v1"
        result = plane_wall_steady_v1(request);
    otherwise
        error("ThermalAgent:ModelNotAllowed", "Model is not allow-listed.");
end

response_json = jsonencode(result);
end
