-- A small XML reader for Android's package lists. No DTDs or external entities.
local M = {}

local function name(value)
	return value:match("^[%a_][%w_.:%-]*$") ~= nil
end

local function utf8(number)
	if
		number == 9
		or number == 10
		or number == 13
		or (number >= 32 and number <= 1114111 and not (number >= 55296 and number <= 57343))
	then
		if number < 128 then
			return string.char(number)
		end
		if number < 2048 then
			return string.char(192 + math.floor(number / 64), 128 + number % 64)
		end
		if number < 65536 then
			return string.char(224 + math.floor(number / 4096), 128 + math.floor(number / 64) % 64, 128 + number % 64)
		end
		return string.char(
			240 + math.floor(number / 262144),
			128 + math.floor(number / 4096) % 64,
			128 + math.floor(number / 64) % 64,
			128 + number % 64
		)
	end
	error("Invalid XML character")
end

local function decode(value)
	local entities = { amp = "&", lt = "<", gt = ">", quot = '"', apos = "'" }
	if value:gsub("&[^;]*;", ""):find("&", 1, true) then
		error("Unescaped XML ampersand")
	end
	return (
		value:gsub("&([^;]*);", function(entity)
			if entities[entity] then
				return entities[entity]
			end
			local number
			if entity:match("^#x%x+$") then
				number = tonumber(entity:sub(3), 16)
			elseif entity:match("^#%d+$") then
				number = tonumber(entity:sub(2))
			end
			if number then
				return utf8(number)
			end
			error("Unsupported XML entity: &" .. entity .. ";")
		end)
	)
end

function M.parse(source)
	if type(source) ~= "string" or #source > 16777216 then
		error("XML exceeds 16 MiB")
	end
	source = source:gsub("^\239\187\191", "")
	local stack, root, position = {}, nil, 1
	local function append(text, raw)
		if #stack == 0 then
			if text:find("%S") then
				error("Unexpected text outside XML root")
			end
		else
			stack[#stack].text = stack[#stack].text .. (raw and text or decode(text))
		end
	end
	while position <= #source do
		local start = source:find("<", position, true)
		if not start then
			append(source:sub(position))
			break
		end
		append(source:sub(position, start - 1))
		if source:sub(start, start + 3) == "<!--" then
			local ending = source:find("-->", start + 4, true)
			if not ending then
				error("Unclosed XML comment")
			end
			position = ending + 3
		elseif source:sub(start, start + 8) == "<![CDATA[" then
			local ending = source:find("]]>", start + 9, true)
			if not ending or #stack == 0 then
				error("Invalid XML CDATA")
			end
			append(source:sub(start + 9, ending - 1), true)
			position = ending + 3
		elseif source:sub(start, start + 1) == "<?" then
			local ending = source:find("?>", start + 2, true)
			if not ending then
				error("Unclosed XML instruction")
			end
			position = ending + 2
		elseif source:sub(start, start + 1) == "<!" then
			error("XML document declarations are not supported")
		else
			local ending, quote = start + 1, nil
			while ending <= #source do
				local char = source:sub(ending, ending)
				if quote then
					if char == quote then
						quote = nil
					end
				elseif char == '"' or char == "'" then
					quote = char
				elseif char == ">" then
					break
				end
				ending = ending + 1
			end
			if ending > #source then
				error("Unclosed XML tag")
			end
			local tag = source:sub(start + 1, ending - 1)
			if tag:sub(1, 1) == "/" then
				local closing = tag:match("^/([^%s]+)%s*$")
				if #stack == 0 or closing ~= stack[#stack].qualified then
					error("Mismatched XML tag")
				end
				table.remove(stack)
			else
				local empty = tag:match("/%s*$") ~= nil
				if empty then
					tag = tag:gsub("/%s*$", "")
				end
				local qualified, rest = tag:match("^([^%s]+)(.*)$")
				if not qualified or not name(qualified) then
					error("Invalid XML tag")
				end
				local node = {
					name = qualified:match("([^:]+)$"),
					qualified = qualified,
					attrs = {},
					children = {},
					text = "",
				}
				while rest:find("%S") do
					local key, separator, value, tail = rest:match("^%s+([^%s=]+)%s*=%s*(['\"])(.-)%2(.*)$")
					if not key or not name(key) or node.attrs[key] ~= nil or value:find("<", 1, true) then
						error("Invalid XML attribute")
					end
					node.attrs[key] = decode(value)
					rest = tail
				end
				if #stack == 0 then
					if root then
						error("Multiple XML roots")
					end
					root = node
				else
					local children = stack[#stack].children
					children[#children + 1] = node
				end
				if not empty then
					if #stack >= 128 then
						error("XML nesting exceeds 128 levels")
					end
					stack[#stack + 1] = node
				end
			end
			position = ending + 1
		end
	end
	if not root or #stack ~= 0 then
		error("Incomplete XML document")
	end
	return root
end

function M.child(node, name)
	if node then
		for _, child in ipairs(node.children) do
			if child.name == name then
				return child
			end
		end
	end
end

function M.text(node, name)
	local child = M.child(node, name)
	return child and child.text:match("^%s*(.-)%s*$") or ""
end

return M
