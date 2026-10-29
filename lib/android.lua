local common = require("common")
local catalog = require("catalog")
local file = require("file")
local json = require("json")
local M = {}
local sdk = require("sdk")
local cli_base = "https://dl.google.com/android/cli/latest/"

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

function M.platform(system, arch)
	local os_name = ({ linux = "linux", darwin = "darwin" })[system]
	local cpu = ({ amd64 = "x86_64", x86_64 = "x86_64", arm64 = "arm64", aarch64 = "arm64" })[arch]
	if not os_name or not cpu then
		error("No Android CLI download for " .. tostring(system) .. "/" .. tostring(arch))
	end
	return os_name .. "_" .. cpu
end

function M.checksum(text)
	local digest, rest = text:match("^%s*(%x+)(.-)%s*$")
	rest = rest and common.trim(rest)
	if
		not digest
		or #digest ~= 64
		or (rest ~= "" and rest ~= "android" and rest ~= "*android" and rest ~= "./android" and rest ~= "*./android")
	then
		error("Google returned an invalid Android CLI checksum")
	end
	return digest:lower()
end

function M.resolve_cli()
	local candidate = common.trim(common.exec({ "sh", "-c", "command -v android || :" }))
	if candidate ~= "" then
		-- mise normally removes its shims from hook PATH. Skip recognizable leftovers.
		local stat = file.stat(candidate)
		if stat and not candidate:match("/mise/shims/") then
			local resolved =
				common.trim(common.exec({ "sh", "-c", 'if [ -L "$1" ]; then readlink "$1"; fi', "sh", candidate }))
			if not resolved:match("/?mise$") then
				return candidate
			end
		end
	end
	local platform = M.platform(RUNTIME.osType, RUNTIME.archType)
	local url = cli_base .. platform .. "/android"
	local expected = M.checksum(common.fetch(url .. ".sha256"))
	local directory = assert(RUNTIME.cacheDirPath, "mise could not create its cache folder")
		.. "/android/"
		.. platform
		.. "/"
		.. expected
	local executable = directory .. "/android"
	local stat = file.stat(executable)
	if stat and stat.is_file and common.sha256(executable) == expected then
		common.exec({ "chmod", "755", executable })
		return executable
	end
	local temporary = common.temp(directory)
	local ok, message = pcall(function()
		print("Downloading " .. url)
		common.download(url, temporary, 67108864)
		if common.sha256(temporary) ~= expected then
			error("Android CLI checksum mismatch; download was not installed")
		end
		common.exec({ "chmod", "755", temporary })
		file.move(temporary, executable)
	end)
	os.remove(temporary)
	if not ok then
		error(message)
	end
	return executable
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

function M.preflight(explicit, installed, options)
	local seen = {}
	local function check(package, options)
		local identity = package.package .. "@" .. package.revision
		if seen[identity] then
			return
		end
		seen[identity] = true
		for _, dependency in ipairs(package.dependencies or {}) do
			local requested = explicit[dependency.package]
			local candidate = requested and requested.package or sdk.installed(dependency.package)
			if not requested and (not candidate or common.less(candidate.revision, dependency.revision)) then
				candidate = M.plan(dependency.package, "latest", options)
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
			check(candidate, requested and requested.options or options)
		end
	end
	for _, name in ipairs(common.keys(explicit)) do
		local entry = explicit[name]
		check(entry.package, entry.options)
	end
	for _, package in ipairs(installed or {}) do
		check(package, options)
	end
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
	local executable = M.resolve_cli()
	common.mkdir(sdk.root())
	local arguments = {
		executable,
		"--sdk",
		sdk.root(),
		"sdk",
		"install",
		"--force",
		package.package .. "@" .. common.cli_revision(package.revision),
	}
	if options.channel ~= "stable" then
		arguments[#arguments + 1] = "--" .. options.channel
	end
	print("download / install SDK packages")
	local ok, message = pcall(common.exec, arguments, options.timeout)
	sdk.changed()
	if not ok then
		error(message)
	end
	print("verify SDK packages")
	local actual = sdk.verify(package)
	sdk.verify_dependencies(package)
	sdk.verify_dependencies(actual)
	sdk.save(ctx, options, package)
	return {}
end

function M.environment(ctx)
	local _, options = request(ctx, true)
	return sdk.environment(ctx, options)
end

function M.uninstall(ctx)
	request(ctx, true)
	local record = sdk.record(ctx)
	if not record then
		return
	end
	local actual = sdk.installed(record.package.package)
	-- An old mise receipt must not remove a newer shared package.
	if not actual or actual.revision ~= record.package.revision then
		return
	end
	local ok, message = pcall(common.exec, {
		M.resolve_cli(),
		"--sdk",
		sdk.root(),
		"sdk",
		"remove",
		record.package.package,
	}, common.options(ctx.options, ctx.tool).timeout)
	sdk.changed()
	if not ok then
		error(message)
	end
end

return M
