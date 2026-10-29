local common = require("common")
local xml = require("xml")
local M = {}
local repositories = {}
M.default_url = "https://dl.google.com/android/repository/repository2-3.xml"

function M.repository_url(tool, options)
	if tool:sub(1, 14) == "system-images/" then
		local api, tag, abi = tool:match("^system%-images/([^/]+)/([^/]+)/([^/]+)$")
		if not api or not abi then
			error("System images need system-images/API/TAG/ABI")
		end
		return options.repository_url
			or ("https://dl.google.com/android/repository/sys-img/" .. tag .. "/sys-img2-3.xml")
	end
	return options.repository_url or M.default_url
end

local function archive(node, system, architecture)
	local host = ({ linux = "linux", darwin = "macosx" })[system]
	local arch = ({ amd64 = "x64", x86_64 = "x64", arm64 = "aarch64", aarch64 = "aarch64" })[architecture]
	if not node or not host or not arch then
		return nil
	end
	for _, item in ipairs(node.children) do
		if item.name == "archive" then
			local os_name, cpu, bits =
				xml.text(item, "host-os"), xml.text(item, "host-arch"), xml.text(item, "host-bits")
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
		result = result .. "-rc." .. preview
	end
	return common.revision(result)
end

local function select_version(path, tool)
	if common.is_sdk(tool) then
		local api = path:match("^platforms/android%-(%d[%d%.]*)$")
		return api and common.revision(api) or nil
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

local function versions(root, tool, channel, system, architecture, url)
	common.package(tool)
	if root.name ~= "sdk-repository" and root.name ~= "sdk-sys-img" then
		error("Not an Android package list")
	end
	local maximum = assert(common.channels[channel], "Unknown release channel")
	local result = {}
	for _, node in ipairs(root.children) do
		if node.name == "remotePackage" then
			local path = (node.attrs.path or ""):gsub(";", "/")
			local selected = select_version(path, tool)
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
						local download = archive(xml.child(node, "archives"), system, architecture)
						if download then
							local checksum = xml.child(download, "checksum")
							local package = {
								package = path,
								revision = actual,
								version = selected,
								download = {
									url = absolute_url(url, xml.text(download, "url")),
									checksum_type = checksum and (checksum.attrs.type or "sha1") or "",
									checksum = checksum and common.trim(checksum.text) or "",
								},
							}
							local previous = result[selected]
							if previous then
								if common.is_sdk(tool) and previous.package == path and previous.revision ~= actual then
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

function M.parse(data, tool, channel, system, architecture, url)
	return versions(
		xml.parse(data),
		tool,
		channel or "stable",
		system or RUNTIME.osType,
		architecture or RUNTIME.archType,
		url or M.default_url
	)
end

function M.versions(tool, options)
	local url = M.repository_url(tool, options)
	if not repositories[url] then
		repositories[url] = xml.parse(common.fetch(url))
	end
	return versions(repositories[url], tool, options.channel, RUNTIME.osType, RUNTIME.archType, url)
end

return M
