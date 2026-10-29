local common = require("common")
local sdk = require("sdk")
local file = require("file")
local M = {}

local function download(package, timeout)
	local item = assert(package.download, "Missing archive for " .. package.package)
	local length = ({ sha1 = 40, sha256 = 64, sha512 = 128 })[item.checksum_type]
	if not length or type(item.checksum) ~= "string" or #item.checksum ~= length or item.checksum:find("[^%x]") then
		error("Missing or invalid archive checksum for " .. package.package)
	end
	if not item.size or item.size < 1 or item.size ~= math.floor(item.size) or item.size > 9007199254740991 then
		error("Missing or invalid archive size for " .. package.package)
	end
	common.url(item.url)
	local digest = item.checksum:lower()
	local directory = assert(RUNTIME.cacheDirPath, "mise did not provide a cache folder")
		.. "/archives/"
		.. item.checksum_type
		.. "/"
		.. digest
	local archive = directory .. "/package.zip"
	local stat = file.stat(archive)
	if stat and stat.is_file and stat.size == item.size and common.digest(archive, item.checksum_type) == digest then
		return archive
	end
	local temporary = common.temp(directory)
	local ok, message = pcall(function()
		print("Downloading " .. item.url)
		common.download(item.url, temporary, item.size, timeout)
		print("Verifying " .. package.package .. " checksum")
		if file.stat(temporary).size ~= item.size or common.digest(temporary, item.checksum_type) ~= digest then
			error("Archive checksum or size mismatch for " .. package.package)
		end
		assert(os.rename(temporary, archive))
	end)
	os.remove(temporary)
	if not ok then
		error(message)
	end
	return archive
end

local function package_root(directory)
	if file.exists(directory .. "/source.properties") then
		return directory
	end
	local root
	for _, child in ipairs(file.list(directory)) do
		if common.is_dir(child) and file.exists(child .. "/source.properties") then
			if root then
				error("Archive contains multiple Android packages")
			end
			root = child
		end
	end
	return assert(root, "Archive is missing Android source.properties")
end

local function accept_license(package, workspace)
	local license = package.license
	if not license then
		return
	end
	if type(license.text) ~= "string" or license.text == "" then
		error("Package list is missing the license text for " .. package.package)
	end
	local source = workspace .. "/license"
	common.atomic(source, license.text)
	local digest = common.digest(source, "sha1")
	local path = sdk.root() .. "/licenses/" .. license.id
	local text = file.exists(path) and common.read(path) or ""
	for line in text:gmatch("[^\r\n]+") do
		if line == digest then
			return
		end
	end
	common.atomic(path, text .. ((text == "" or text:sub(-1) == "\n") and "" or "\n") .. digest .. "\n")
end

function M.install(packages, timeout)
	local workspace = common.temp_dir(sdk.data_dir() .. "/android")
	local prepared, changed = {}, {}
	local ok, message = pcall(function()
		for _, name in ipairs(common.keys(packages)) do
			local package = packages[name]
			local actual = sdk.installed(name)
			if not actual or actual.revision ~= package.revision then
				local archive = download(package, timeout)
				local directory = workspace .. "/" .. (#prepared + 1)
				print("unpack " .. name)
				-- NDK ZIPs contain symbolic links that mise's extractor currently flattens.
				common.exec({ "unzip", "-q", "-o", archive, "-d", directory }, timeout)
				local root = package_root(directory)
				local content = sdk.read(root, name)
				if not content or content.revision ~= package.revision then
					error(
						"Expected "
							.. name
							.. "@"
							.. package.revision
							.. ", found "
							.. (content and content.revision or "missing")
					)
				end
				prepared[#prepared + 1] = { package = package, root = root, backup = directory .. ".previous" }
				common.atomic(root .. "/package.xml", assert(package.metadata, "Missing Android package metadata"))
			end
		end
		for _, entry in ipairs(prepared) do
			local destination = sdk.root() .. "/" .. entry.package.package
			common.mkdir(assert(destination:match("^(.*)/[^/]+$")))
			local previous = file.exists(destination)
			if previous then
				assert(os.rename(destination, entry.backup))
			end
			changed[#changed + 1] = { destination = destination, backup = previous and entry.backup }
			assert(os.rename(entry.root, destination))
			accept_license(entry.package, workspace)
		end
		for _, package in pairs(packages) do
			sdk.verify_dependencies(sdk.verify(package))
		end
	end)
	if not ok then
		for index = #changed, 1, -1 do
			local entry = changed[index]
			common.remove(entry.destination)
			if entry.backup then
				assert(os.rename(entry.backup, entry.destination))
			end
		end
	end
	common.remove(workspace)
	if #changed > 0 then
		sdk.changed()
	end
	if not ok then
		error(message)
	end
end

function M.remove(package)
	local actual = sdk.installed(package.package)
	if actual and actual.revision == package.revision then
		local destination = sdk.root() .. "/" .. package.package
		local trash = common.temp_dir(sdk.data_dir() .. "/android")
		assert(os.rename(destination, trash .. "/package"))
		sdk.changed()
		common.remove(trash)
	end
end

return M
