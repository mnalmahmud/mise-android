local M = {}
local root = assert(package.path:match("^(.-)%?%.lua"), "Missing plugin module path")

function M.run(action, ctx)
    if RUNTIME.osType ~= "linux" and RUNTIME.osType ~= "darwin" and RUNTIME.osType ~= "macos" then
        error("mise-android supports Linux and macOS; Windows is not supported")
    end
    local json = require("json")
    local cmd = require("cmd")
    -- Values are passed through the environment, never interpolated into shell code.
    local output = cmd.exec('python3 -B "$MISE_ANDROID_HELPER" "$MISE_ANDROID_ACTION"', {
        env = {
            MISE_ANDROID_HELPER = root .. "lib/android_backend.py",
            MISE_ANDROID_ACTION = action,
            MISE_ANDROID_REQUEST = json.encode(ctx),
        },
    })
    return json.decode(output)
end

return M
