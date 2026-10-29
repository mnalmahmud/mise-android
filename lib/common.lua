local M = {}

M.families = { ndk = true, ["build-tools"] = true, ["cmdline-tools"] = true, cmake = true }
M.channels = { stable = 0, beta = 1, canary = 3 }

function M.trim(value)
	return (value:gsub("^%s+", ""):gsub("%s+$", ""))
end

function M.package(value)
	if type(value) ~= "string" or value == "" or value:find("//", 1, true) or value:sub(-1) == "/" then
		error("Invalid Android package name: " .. tostring(value))
	end
	for part in value:gmatch("[^/]+") do
		if not part:match("^[%w_][%w_.+%-]*$") then
			error("Invalid Android package name: " .. value)
		end
	end
	if value:sub(1, 1) == "/" then
		error("Package names must not start with /")
	end
	return value
end

function M.is_sdk(tool)
	return tool == "sdk" or tool:sub(1, 4) == "sdk/"
end

function M.revision(value)
	if type(value) ~= "string" then
		error("Android versions must be strings")
	end
	value = M.trim(value):lower()
	local base, kind, number = value:match("^(%d[%d%.]*)[%s%-]*(%a+)[%.%s]*(%d+)$")
	if not base then
		base = value:match("^(%d[%d%.]*)$")
	end
	if
		not base
		or base:sub(-1) == "."
		or base:find("..", 1, true)
		or (kind and kind ~= "alpha" and kind ~= "beta" and kind ~= "rc")
	then
		error("Invalid Android version: " .. value)
	end
	local parts = {}
	for part in base:gmatch("[^.]+") do
		if #part > 15 then
			error("Android version number is too large")
		end
		parts[#parts + 1] = string.format("%.0f", tonumber(part))
	end
	local result = table.concat(parts, ".")
	if kind then
		if #number > 15 then
			error("Android preview number is too large")
		end
		result = result .. "-" .. kind .. "." .. tonumber(number)
	end
	return result
end

function M.less(left, right)
	local function parts(value)
		local normalized = M.revision(value)
		local base, kind, number = normalized:match("^(.-)%-(%a+)%.(%d+)$")
		local result = {}
		for part in (base or normalized):gmatch("%d+") do
			result[#result + 1] = tonumber(part)
		end
		return result, ({ alpha = 0, beta = 1, rc = 2 })[kind] or 3, tonumber(number) or 0
	end
	local a, ak, an = parts(left)
	local b, bk, bn = parts(right)
	for index = 1, math.max(#a, #b) do
		if (a[index] or 0) ~= (b[index] or 0) then
			return (a[index] or 0) < (b[index] or 0)
		end
	end
	if ak ~= bk then
		return ak < bk
	end
	return an < bn
end

function M.keys(values)
	local result = {}
	for key in pairs(values) do
		result[#result + 1] = key
	end
	table.sort(result)
	return result
end

function M.url(value)
	if type(value) ~= "string" or value:find("[%s%c]") then
		error("repository_url must be an HTTPS address or an absolute file:// address")
	end
	local host = value:match("^https://([^/?#]+)")
	if host then
		local name, port
		if host:sub(1, 1) == "[" then
			name, port = host:match("^(%[[%x:%.]+%]):(%d+)$")
			name = name or host:match("^%[[%x:%.]+%]$")
		else
			name, port = host:match("^([%w_.%-]+):(%d+)$")
			name = name or host:match("^[%w_.%-]+$")
		end
		if name and (not port or (tonumber(port) >= 1 and tonumber(port) <= 65535)) then
			return value
		end
	end
	if value:match("^file:///") or value:match("^file://localhost/") then
		return value
	end
	error("repository_url must be an HTTPS address or an absolute file:// address")
end

function M.options(raw, tool)
	if raw == nil then
		raw = {}
	end
	if type(raw) ~= "table" then
		error("Tool settings must be a table")
	end
	local allowed = { channel = true, packages = true, timeout = true, repository_url = true }
	for key in pairs(raw) do
		if not allowed[key] then
			error("Unknown Android setting: " .. tostring(key))
		end
	end
	local channel = raw.channel == nil and "stable" or raw.channel
	if type(channel) ~= "string" or not M.channels[channel] then
		error("channel must be stable, beta, or canary")
	end
	local timeout = raw.timeout == nil and 1800 or raw.timeout
	if (type(timeout) ~= "number" and type(timeout) ~= "string") or not tostring(timeout):match("^%d+$") then
		error("timeout must be a whole number from 1 to 86400 seconds")
	end
	timeout = tonumber(timeout)
	if not timeout or timeout < 1 or timeout > 86400 then
		error("timeout must be a whole number from 1 to 86400 seconds")
	end
	local packages = {}
	if raw.packages ~= nil then
		if tool and not M.is_sdk(tool) then
			error("packages is only available for android:sdk")
		end
		if type(raw.packages) ~= "table" then
			error("packages must be a table of names and versions")
		end
		for name, version in pairs(raw.packages) do
			M.package(name)
			if M.is_sdk(name) then
				error("An SDK cannot include another SDK")
			end
			packages[name] = version == "latest" and version or M.revision(version)
		end
	end
	local repository_url
	if raw.repository_url ~= nil then
		repository_url = M.url(raw.repository_url)
	end
	return { channel = channel, timeout = timeout, packages = packages, repository_url = repository_url }
end

function M.quote(value)
	return "'" .. tostring(value):gsub("'", "'\\''") .. "'"
end

function M.exec(arguments, timeout)
	local quoted = {}
	for _, value in ipairs(arguments) do
		quoted[#quoted + 1] = M.quote(value)
	end
	return require("cmd").exec(table.concat(quoted, " "), { timeout = timeout or 30 })
end

function M.mkdir(path)
	M.exec({ "mkdir", "-p", path })
end

function M.temp(directory)
	M.mkdir(directory)
	return M.trim(M.exec({ "mktemp", directory .. "/.mise-android.XXXXXXXX" }))
end

function M.read(path)
	return require("file").read(path)
end

function M.is_dir(path)
	local stat = require("file").stat(path)
	return stat and stat.is_dir or false
end

function M.atomic(path, content)
	local temporary = M.temp(assert(path:match("^(.*)/[^/]+$")))
	local ok, message = pcall(function()
		local stream = assert(io.open(temporary, "wb"))
		local written, reason = stream:write(content)
		local closed, close_reason = stream:close()
		assert(written, reason)
		assert(closed, close_reason)
		require("file").move(temporary, path)
	end)
	os.remove(temporary)
	if not ok then
		error(message)
	end
end

function M.download(url, destination, maximum, timeout)
	M.url(url)
	local ok, message = pcall(M.exec, {
		"curl",
		"--fail",
		"--silent",
		"--show-error",
		"--location",
		"--proto",
		"=https",
		"--proto-redir",
		"=https",
		"--connect-timeout",
		"30",
		"--max-time",
		tostring(timeout or 120),
		"--max-filesize",
		tostring(maximum or 16777216),
		"--output",
		destination,
		url,
	}, (timeout or 120) + 5)
	if not ok then
		os.remove(destination)
		error("Download failed: " .. tostring(message))
	end
	local stat = require("file").stat(destination)
	if not stat or not stat.is_file or stat.size > (maximum or 16777216) then
		os.remove(destination)
		error("Downloaded file is missing or too large")
	end
end

function M.fetch(url)
	M.url(url)
	if url:match("^file://") then
		local path = url:gsub("^file://localhost", ""):gsub("^file://", "")
		path = path:gsub("%%(%x%x)", function(hex)
			return string.char(tonumber(hex, 16))
		end)
		local stat = require("file").stat(path)
		if not stat or not stat.is_file or stat.size > 16777216 then
			error("Local package list is missing or exceeds 16 MiB: " .. path)
		end
		return M.read(path)
	end
	local temporary = M.temp(assert(RUNTIME.cacheDirPath, "mise could not create its cache folder"))
	local ok, result = pcall(function()
		M.download(url, temporary)
		return M.read(temporary)
	end)
	os.remove(temporary)
	if not ok then
		error(result)
	end
	return result
end

function M.sha256(path)
	local args = RUNTIME.osType == "darwin" and { "shasum", "-a", "256", path } or { "sha256sum", path }
	local digest = M.exec(args):match("^(%x+)")
	if not digest or #digest ~= 64 then
		error("Could not check the download: " .. path)
	end
	return digest:lower()
end

return M
