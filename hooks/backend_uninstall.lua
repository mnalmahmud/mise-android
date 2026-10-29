function PLUGIN:BackendUninstall(ctx)
	return require("android").uninstall(ctx)
end
