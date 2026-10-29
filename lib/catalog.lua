local common = require("common")
local xml = require("xml")
local M = {}
local repositories = {}
local linux_native = { ndk = true, ["platform-tools"] = true, ["build-tools"] = true, cmake = true, emulator = true }
M.default_url = "https://dl.google.com/android/repository/repository2-3.xml"

function M.repository_url(tool, options)
	common.tool(tool)
	if tool == "system-image" then
		return options.repository_url
			or (
				"https://dl.google.com/android/repository/sys-img/"
				.. (options.variant or "google_apis")
				.. "/sys-img2-3.xml"
			)
	end
	return options.repository_url or M.default_url
end

local function archive(node, system, architecture, path)
	local host = ({ linux = "linux", darwin = "macosx" })[system]
	local arch = ({ amd64 = "x64", x86_64 = "x64", arm64 = "aarch64", aarch64 = "aarch64" })[architecture]
	if not node or not host or not arch then
		return nil
	end
	for _, item in ipairs(node.children) do
		if item.name == "archive" then
			local os_name, cpu, bits =
				xml.text(item, "host-os"), xml.text(item, "host-arch"), xml.text(item, "host-bits")
			-- These native Linux packages omit host-arch in older repository entries.
			if cpu == "" and os_name == "linux" and linux_native[path:match("^[^/]+")] then
				cpu = "x64"
			end
			if (os_name == "" or os_name == host) and (cpu == "" or cpu == arch) and (bits == "" or bits == "64") then
				local complete = xml.child(item, "complete")
				if complete and xml.text(complete, "url") ~= "" then
					return complete
				end
			end
		end
	end
end

local function package_revision(node, path)
	if not node then
		error("Missing version for " .. path)
	end
	local parts = {}
	for _, name in ipairs({ "major", "minor", "micro" }) do
		local value = xml.text(node, name)
		if value == "" then
			if name == "major" then
				error("Missing version for " .. path)
			end
		elseif not value:match("^%d+$") then
			error("Invalid version for " .. path)
		else
			parts[#parts + 1] = value
		end
	end
	local result = table.concat(parts, ".")
	local preview = xml.text(node, "preview")
	if preview ~= "" then
		if not preview:match("^%d+$") then
			error("Invalid preview version for " .. path)
		end
		if tonumber(preview) > 0 then
			result = result .. "-rc." .. preview
		end
	end
	return common.revision(result)
end

function M.dependencies(node)
	local result = {}
	local dependencies = xml.child(node, "dependencies")
	for _, dependency in ipairs(dependencies and dependencies.children or {}) do
		if dependency.name == "dependency" then
			local path = common.package((dependency.attrs.path or ""):gsub(";", "/"))
			local minimum = xml.child(dependency, "min-revision")
			result[#result + 1] = {
				package = path,
				revision = minimum and package_revision(minimum, path) or "0",
			}
		end
	end
	return result
end

local function select_version(path, tool, options, architecture)
	if common.is_sdk(tool) then
		local api = path:match("^platforms/android%-(%d[%d%.]*)$")
		return api and common.revision(api) or nil
	elseif tool == "system-image" then
		local api, variant, arch = path:match("^system%-images/android%-(%d[%d%.]*)/([^/]+)/([^/]+)$")
		if
			api
			and variant == (options.variant or "google_apis")
			and arch == (options.arch or common.image_arch(architecture))
		then
			return common.revision(api)
		end
	elseif common.families[tool] then
		local family, version = path:match("^([^/]+)/([^/]+)$")
		if family == tool and version ~= "latest" then
			return common.revision(version)
		end
	elseif path == tool then
		return false
	end
end

local function absolute_url(base, path)
	if path:match("^%a[%w+.-]*:") then
		return path
	end
	if path:sub(1, 1) == "/" then
		return (base:match("^(https://[^/]+)") or "file://") .. path
	end
	return (base:match("^(.*)/") or base) .. "/" .. path
end

local function metadata(root, node)
	local attrs = {}
	for key, value in pairs(root.attrs) do
		if key:match("^xmlns:") then
			attrs[key] = value
		end
	end
	local prefix = "mise"
	while attrs["xmlns:" .. prefix] do
		prefix = prefix .. "_"
	end
	attrs["xmlns:" .. prefix] = "http://schemas.android.com/repository/android/common/02"
	local local_package = { name = "localPackage", attrs = { path = node.attrs.path }, children = {} }
	local keep = {
		["type-details"] = true,
		revision = true,
		["display-name"] = true,
		["uses-license"] = true,
		dependencies = true,
	}
	for _, child in ipairs(node.children) do
		if keep[child.name] then
			local_package.children[#local_package.children + 1] = child
		end
	end
	local children, license = {}, nil
	local reference = xml.child(node, "uses-license")
	if reference then
		local id = common.package(reference.attrs.ref or "")
		if id:find("/", 1, true) then
			error("Invalid Android license name")
		end
		for _, child in ipairs(root.children) do
			if child.name == "license" and child.attrs.id == id then
				children[#children + 1] = child
				license = { id = id, text = child.text }
				break
			end
		end
		if not license then
			license = { id = id }
		end
	end
	children[#children + 1] = local_package
	return '<?xml version="1.0" encoding="UTF-8"?>\n' .. xml.serialize({
		qualified = prefix .. ":repository",
		attrs = attrs,
		children = children,
	}) .. "\n",
		license
end

local function versions(root, tool, channel, system, architecture, url, options)
	common.tool(tool)
	if root.name ~= "sdk-repository" and root.name ~= "sdk-sys-img" then
		error("Not an Android package list")
	end
	local maximum = assert(common.channels[channel], "Unknown release channel")
	local result = {}
	for _, node in ipairs(root.children) do
		if node.name == "remotePackage" then
			local path = (node.attrs.path or ""):gsub(";", "/")
			local selected = select_version(path, tool, options or {}, architecture)
			if selected ~= nil then
				common.package(path)
				local channel_node = xml.child(node, "channelRef")
				local channel_id = channel_node and channel_node.attrs.ref or "channel-0"
				local number = channel_id:match("^channel%-(%d+)$")
				if not number then
					error("Invalid channel for " .. path)
				end
				if tonumber(number) <= maximum then
					local actual = package_revision(xml.child(node, "revision"), path)
					if channel ~= "stable" or not actual:find("-", 1, true) then
						selected = selected or actual
						if actual:find("-", 1, true) and not selected:find("-", 1, true) then
							selected = selected .. actual:match("(%-.*)$")
						end
						local download = archive(xml.child(node, "archives"), system, architecture, path)
						if download then
							local checksum = xml.child(download, "checksum")
							local package_xml, license = metadata(root, node)
							local package = {
								package = path,
								revision = actual,
								version = selected,
								dependencies = M.dependencies(node),
								metadata = package_xml,
								license = license,
								download = {
									url = absolute_url(url, xml.text(download, "url")),
									checksum_type = checksum and (checksum.attrs.type or "sha1") or "",
									checksum = checksum and common.trim(checksum.text) or "",
									size = tonumber(xml.text(download, "size")),
								},
							}
							local previous = result[selected]
							if previous then
								if
									(common.is_sdk(tool) or tool == "system-image")
									and previous.package == path
									and previous.revision ~= actual
								then
									if common.less(previous.revision, actual) then
										result[selected] = package
									end
								elseif
									previous.package ~= path
									or previous.revision ~= actual
									or previous.download.url ~= package.download.url
									or previous.download.checksum ~= package.download.checksum
								then
									error("More than one package matches " .. tool .. "@" .. selected)
								end
							else
								result[selected] = package
							end
						end
					end
				end
			end
		end
	end
	if next(result) == nil then
		error("No " .. channel .. " versions of " .. tool .. " are available for this machine")
	end
	return result
end

function M.parse(data, tool, channel, system, architecture, url, options)
	return versions(
		xml.parse(data),
		tool,
		channel or "stable",
		system or RUNTIME.osType,
		architecture or RUNTIME.archType,
		url or M.default_url,
		options
	)
end

function M.versions(tool, options)
	local url = M.repository_url(tool, options)
	if not repositories[url] then
		repositories[url] = xml.parse(common.fetch(url))
	end
	return versions(repositories[url], tool, options.channel, RUNTIME.osType, RUNTIME.archType, url, options)
end

return M
