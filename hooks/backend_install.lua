function PLUGIN:BackendInstall(ctx)
    return require("bridge").run("install", ctx)
end
