local common = require("common")
local catalog = require("catalog")
local xml = require("xml")
local file = require("file")
local json = require("json")
local M = {}
local record_name = ".mise-android-package.json"

function M.data_dir()
	local directory = os.getenv("MISE_DATA_DIR")
		or (
			(os.getenv("XDG_DATA_HOME") or (assert(os.getenv("HOME"), "HOME is required") .. "/.local/share"))
			.. "/mise"
		)
	if directory:sub(1, 1) ~= "/" then
		error("mise's data folder must be an absolute path")
	end
	return directory:gsub("/+$", "")
end

function M.root()
	return M.data_dir() .. "/android/sdk"
end

function M.changed()
	-- mise caches hook results against its data folder's modification time.
	common.exec({ "touch", M.data_dir() })
end

function M.installed(path)
	common.package(path)
	local directory = M.root() .. "/" .. path
	if not file.exists(directory .. "/source.properties") then
		return nil
	end
	local revision
	for line in common.read(directory .. "/source.properties"):gmatch("[^\r\n]+") do
		local value = line:match("^%s*Pkg%.Revision%s*=%s*(.-)%s*$")
		if value then
			revision = common.revision(value)
		end
	end
	if not revision then
		error("Installed package has no version: " .. path)
	end
	local dependencies = {}
	if file.exists(directory .. "/package.xml") then
		local root = xml.parse(common.read(directory .. "/package.xml"))
		local node = root.name == "localPackage" and root or xml.child(root, "localPackage")
		if not node or (node.attrs.path or ""):gsub(";", "/") ~= path then
			error("Installed package has the wrong name: " .. path)
		end
		dependencies = catalog.dependencies(node)
	end
	return { package = path, revision = revision, dependencies = dependencies }
end

function M.packages(excluded)
	local result = {}
	local function visit(directory, path, depth)
		if path ~= "" and file.exists(directory .. "/source.properties") then
			if not excluded[path] then
				result[#result + 1] = M.installed(path)
			end
		elseif depth < 4 and common.is_dir(directory) then
			for _, child in ipairs(file.list(directory)) do
				local name = child:match("([^/]+)$")
				if name:match("^[%w_][%w_.+%-]*$") and name ~= "licenses" and common.is_dir(child) then
					visit(child, path == "" and name or path .. "/" .. name, depth + 1)
				end
			end
		end
	end
	visit(M.root(), "", 0)
	return result
end

function M.verify(package, minimum)
	local actual = M.installed(package.package)
	if
		not actual
		or (minimum and common.less(actual.revision, package.revision))
		or (not minimum and actual.revision ~= package.revision)
	then
		error(
			"Expected "
				.. package.package
				.. "@"
				.. package.revision
				.. ", found "
				.. (actual and actual.revision or "missing")
				.. "; run mise install --force for this tool"
		)
	end
	return actual
end

function M.save(ctx, options, package)
	common.atomic(ctx.install_path .. "/" .. record_name, json.encode({
		tool = ctx.tool,
		version = common.revision(ctx.version),
		channel = options.channel,
		variant = options.variant,
		arch = options.arch,
		package = package,
	}) .. "\n")
end

function M.record(ctx)
	local path = ctx.install_path .. "/" .. record_name
	if not file.exists(path) then
		return nil
	end
	local record = json.decode(common.read(path))
	if
		type(record) ~= "table"
		or record.tool ~= ctx.tool
		or record.version ~= common.revision(ctx.version)
		or type(record.package) ~= "table"
	then
		error("Installation record does not match this tool; reinstall it")
	end
	common.package(record.package.package)
	common.revision(record.package.revision)
	return record
end

function M.verify_dependencies(package, seen)
	seen = seen or {}
	if seen[package.package] then
		return
	end
	seen[package.package] = true
	for _, dependency in ipairs(package.dependencies or {}) do
		M.verify_dependencies(M.verify(dependency, true), seen)
	end
end

function M.environment(ctx, options)
	local record = assert(M.record(ctx), "Installation record is missing; reinstall this tool")
	if record.channel ~= options.channel or record.variant ~= options.variant or record.arch ~= options.arch then
		error("Android settings changed; run mise install --force for this tool")
	end
	local actual = M.verify(record.package)
	M.verify_dependencies(record.package)
	M.verify_dependencies(actual)
	local root = M.root()
	local values = { { key = "ANDROID_HOME", value = root } }
	local function path(value)
		if common.is_dir(value) then
			values[#values + 1] = { key = "PATH", value = value }
		end
	end
	path(root .. "/platform-tools")
	path(root .. "/emulator")
	local family = actual.package:match("^[^/]+")
	if family == "ndk" then
		values[#values + 1] = { key = "ANDROID_NDK_HOME", value = root .. "/" .. actual.package }
		path(root .. "/" .. actual.package)
	elseif family == "build-tools" then
		path(root .. "/" .. actual.package)
	elseif family == "cmake" or family == "cmdline-tools" then
		path(root .. "/" .. actual.package .. "/bin")
	end
	return { env_vars = values }
end

return M
