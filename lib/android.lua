local common = require("common")
local catalog = require("catalog")
local json = require("json")
local M = {}
local sdk = require("sdk")

local function request(ctx, installed)
	if RUNTIME.osType ~= "linux" and RUNTIME.osType ~= "darwin" then
		error("mise-android currently supports Linux and macOS")
	end
	local tool = common.tool(ctx.tool)
	local options = common.options(ctx.options, tool)
	if installed then
		if type(ctx.install_path) ~= "string" or ctx.install_path:sub(1, 1) ~= "/" then
			error("mise must provide an absolute installation folder")
		end
		common.revision(ctx.version)
	end
	return tool, options
end

function M.plan(tool, version, options)
	local available = catalog.versions(tool, options)
	if version == "latest" then
		local ordered = common.keys(available)
		table.sort(ordered, common.less)
		version = ordered[#ordered]
	end
	if not available[version] then
		error("Package list does not offer " .. tool .. "@" .. tostring(version))
	end
	return available[version]
end

local function project_packages(ctx, own, options)
	local explicit = { [own.package] = { package = own, options = options } }
	local mise = os.getenv("MISE_BIN") or "mise"
	local tools = json.decode(common.exec({ mise, "ls", "--current", "--json", "--offline" }, 60))
	for _, name in ipairs(common.keys(tools)) do
		local tool = name:match("^android:(.+)$")
		if tool then
			common.tool(tool)
			local versions = tools[name]
			local info = json.decode(common.exec({ mise, "tool", name, "--json" }, 60))
			local raw = {}
			for _, key in ipairs({ "channel", "timeout", "repository_url", "variant", "arch" }) do
				if info.tool_options[key] ~= nil then
					raw[key] = info.tool_options[key]
				end
			end
			local peer_options = common.options(raw, tool)
			local configured = false
			for _, entry in ipairs(versions) do
				configured = configured or entry.version == ctx.version
			end
			for _, entry in ipairs(versions) do
				if tool ~= ctx.tool or configured then
					local package = tool == ctx.tool and entry.version == ctx.version and own
						or M.plan(tool, entry.version, peer_options)
					local previous = explicit[package.package]
					if previous and previous.package.revision ~= package.revision then
						error("The SDK cannot contain two versions of " .. package.package)
					end
					explicit[package.package] =
						{ package = package, options = package == own and options or peer_options }
				end
			end
		end
	end
	return explicit
end

function M.preflight(explicit, installed, options, roots)
	local resolved, settings = {}, {}
	for _, package in ipairs(installed or {}) do
		resolved[package.package], settings[package.package] = package, options
	end
	for name, entry in pairs(roots or explicit) do
		resolved[name], settings[name] = entry.package, entry.options
	end
	local changed = true
	while changed do
		changed = false
		for _, name in ipairs(common.keys(resolved)) do
			local package = resolved[name]
			for _, dependency in ipairs(package.dependencies or {}) do
				local requested = explicit[dependency.package]
				local candidate = requested and requested.package or resolved[dependency.package]
				if not requested and (not candidate or common.less(candidate.revision, dependency.revision)) then
					candidate = M.plan(dependency.package, "latest", settings[name])
				end
				if common.less(candidate.revision, dependency.revision) then
					error(
						package.package
							.. " requires "
							.. dependency.package
							.. " >= "
							.. dependency.revision
							.. "; the requested version is "
							.. candidate.revision
					)
				end
				local previous = resolved[dependency.package]
				if not previous or previous.revision ~= candidate.revision then
					resolved[dependency.package] = candidate
					settings[dependency.package] = requested and requested.options or settings[name]
					changed = true
				end
			end
		end
	end
	return resolved
end

function M.versions(ctx)
	local tool, options = request(ctx)
	local versions = common.keys(catalog.versions(tool, options))
	table.sort(versions, common.less)
	return { versions = versions }
end

function M.install(ctx)
	local tool, options = request(ctx, true)
	print("resolve packages")
	local package = M.plan(tool, common.revision(ctx.version), options)
	local project = project_packages(ctx, package, options)
	M.preflight(project, sdk.packages(project), options)
	local lock = require("lock")
	lock.run(sdk.data_dir() .. "/android/install.lock", options.timeout, function()
		local installed = sdk.packages({ [package.package] = true })
		M.preflight(project, sdk.packages(project), options)
		local resolved = M.preflight(project, installed, options, { [package.package] = project[package.package] })
		require("installer").install(resolved, options.timeout)
		sdk.save(ctx, options, package)
	end)
	return {}
end

function M.environment(ctx)
	local _, options = request(ctx, true)
	return sdk.environment(ctx, options)
end

function M.uninstall(ctx)
	local _, options = request(ctx, true)
	require("lock").run(sdk.data_dir() .. "/android/install.lock", options.timeout, function()
		local record = sdk.record(ctx)
		if record then
			require("installer").remove(record.package)
		end
	end)
end

return M
