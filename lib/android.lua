local common = require("common")
local catalog = require("catalog")
local xml = require("xml")
local file = require("file")
local json = require("json")
local M = {}
local manifest_name = ".mise-android-package.json"
local cli_base = "https://dl.google.com/android/cli/latest/"

local function request(ctx, installed)
	if RUNTIME.osType ~= "linux" and RUNTIME.osType ~= "darwin" then
		error("mise-android currently supports Linux and macOS")
	end
	local tool = common.package(ctx.tool)
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

local function select(tool, version, options)
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

function M.plan(tool, version, options)
	local result, selected = {}, {}
	local function add(package)
		local previous = selected[package.package]
		if previous then
			if previous.revision ~= package.revision then
				error("An SDK cannot contain two versions of " .. package.package)
			end
		else
			selected[package.package] = package
			result[#result + 1] = package
		end
	end
	add(select(tool, version, options))
	for _, name in ipairs(common.keys(options.packages)) do
		add(select(name, options.packages[name], options))
	end
	return result
end

function M.verify(sdk, package)
	local path = sdk .. "/" .. package.package
	local properties = common.read(path .. "/source.properties")
	local actual
	for line in properties:gmatch("[^\r\n]+") do
		local value = line:match("^%s*Pkg%.Revision%s*=%s*(.-)%s*$")
		if value then
			actual = common.revision(value)
		end
	end
	if actual ~= package.revision then
		error("Expected " .. package.package .. "@" .. package.revision .. ", found " .. tostring(actual))
	end
	if file.exists(path .. "/package.xml") then
		local root = xml.parse(common.read(path .. "/package.xml"))
		local local_package = root.name == "localPackage" and root or xml.child(root, "localPackage")
		local identity = local_package and local_package.attrs.path
		if not identity or identity:gsub(";", "/") ~= package.package then
			error("Installed package has the wrong name: " .. path)
		end
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
	local sdk = ctx.install_path .. "/sdk"
	if file.stat(sdk) then
		error("SDK folder already exists; reinstall through mise: " .. sdk)
	end
	local packages = M.plan(tool, common.revision(ctx.version), options)
	local executable = M.resolve_cli()
	common.mkdir(sdk)
	local arguments = {
		executable,
		"--sdk",
		sdk,
		"sdk",
		"install",
	}
	for _, package in ipairs(packages) do
		arguments[#arguments + 1] = package.package .. "@" .. package.revision
	end
	if options.channel ~= "stable" then
		arguments[#arguments + 1] = "--" .. options.channel
	end
	common.exec(arguments, options.timeout)
	for _, package in ipairs(packages) do
		M.verify(sdk, package)
	end
	common.atomic(ctx.install_path .. "/" .. manifest_name, json.encode({
		schema = 1,
		tool = tool,
		version = common.revision(ctx.version),
		channel = options.channel,
		packages = options.packages,
		components = packages,
	}) .. "\n")
	return {}
end

function M.environment(ctx)
	local tool, options = request(ctx, true)
	local manifest = json.decode(common.read(ctx.install_path .. "/" .. manifest_name))
	if
		type(manifest) ~= "table"
		or manifest.schema ~= 1
		or manifest.tool ~= tool
		or manifest.version ~= common.revision(ctx.version)
	then
		error("Installation record does not match " .. tool .. "; reinstall it")
	end
	local stored = common.options({ channel = manifest.channel, packages = manifest.packages })
	if stored.channel ~= options.channel then
		error("Release channel changed; reinstall this tool")
	end
	for _, packages in ipairs({ stored.packages, options.packages }) do
		for name in pairs(packages) do
			if stored.packages[name] ~= options.packages[name] then
				error("SDK packages changed; reinstall this tool")
			end
		end
	end
	if type(manifest.components) ~= "table" or #manifest.components == 0 then
		error("Installation record has no packages; reinstall this tool")
	end
	local sdk, values, paths, ndk = ctx.install_path .. "/sdk", {}, {}, nil
	local function value(key, path)
		values[#values + 1] = { key = key, value = path }
	end
	if common.is_sdk(tool) then
		value("ANDROID_HOME", sdk)
	end
	for _, package in ipairs(manifest.components) do
		if type(package) ~= "table" then
			error("Invalid installed package record")
		end
		common.package(package.package)
		common.revision(package.revision)
		local path = sdk .. "/" .. package.package
		if not common.is_dir(path) then
			error("Installed package is missing: " .. path .. "; reinstall it")
		end
		local family = package.package:match("^[^/]+")
		if family == "ndk" and (not ndk or common.less(ndk.revision, package.revision)) then
			ndk = package
		end
		if family == "cmdline-tools" or family == "cmake" then
			path = path .. "/bin"
		elseif family == "platforms" or family == "system-images" or family == "sources" then
			path = nil
		end
		if path and not paths[path] and common.is_dir(path) then
			paths[path] = true
			value("PATH", path)
		end
	end
	if ndk then
		value("ANDROID_NDK_HOME", sdk .. "/" .. ndk.package)
	end
	return { env_vars = values }
end

return M
