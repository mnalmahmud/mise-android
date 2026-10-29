local common = require("common")
local file = require("file")
local M = {}

local function process_started(pid)
	local ok, value = pcall(common.exec, { "env", "LC_ALL=C", "ps", "-p", pid, "-o", "lstart=" })
	return ok and common.trim(value) or nil
end

function M.run(directory, timeout, run)
	local pid = common.trim(common.exec({ "sh", "-c", 'printf "%s" "$PPID"' }))
	assert(pid:match("^[1-9]%d*$"), "Could not identify the mise process")
	local started = assert(process_started(pid), "Could not identify the mise process start time")
	local parent = assert(directory:match("^(.*)/[^/]+$"))
	local claim = common.temp_dir(parent)
	local owner = pid .. "-" .. claim:match("([^/]+)$")
	common.atomic(claim .. "/" .. owner, started)
	local deadline = os.time() + timeout
	local ok, result = pcall(function()
		while not os.rename(claim, directory) do
			local exists, owners = pcall(file.list, directory)
			if exists then
				for _, path in ipairs(owners) do
					local owner_pid = path:match("/([1-9]%d*)%-[^/]+$")
					if owner_pid then
						local readable, previous = pcall(common.read, path)
						if readable and process_started(owner_pid) ~= previous then
							os.remove(path)
						end
					end
				end
				-- Only an empty lock can be reclaimed; an active claim always has an owner file.
				os.remove(directory)
			end
			if os.time() >= deadline then
				error("Timed out waiting for the Android SDK installation lock")
			end
			print("waiting for SDK installation")
			common.exec({ "sleep", "1" })
		end
		return run()
	end)
	if file.exists(directory .. "/" .. owner) then
		os.remove(directory .. "/" .. owner)
		os.remove(directory)
	end
	common.remove(claim)
	if not ok then
		error(result)
	end
	return result
end

return M
