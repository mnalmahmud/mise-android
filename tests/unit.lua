-- These checks run both in Lua 5.1 and in mise's embedded Lua interpreter.
local root = RUNTIME and RUNTIME.pluginDirPath or "."
if not RUNTIME then
	RUNTIME = { osType = "linux", archType = "amd64", pluginDirPath = root }
	package.path = root .. "/lib/?.lua;" .. package.path
	package.preload.file = function()
		return {}
	end
	package.preload.json = function()
		return {}
	end
end
local common = require("common")
local xml = require("xml")
local catalog = require("catalog")
local android = require("android")
local count = 0
local function check(name, run)
	local ok, message = pcall(run)
	if not ok then
		error(name .. ": " .. tostring(message))
	end
	count = count + 1
end
local function equal(actual, expected)
	assert(actual == expected, "expected " .. tostring(expected) .. ", got " .. tostring(actual))
end
local function rejects(run)
	assert(not pcall(run), "invalid input was accepted")
end
local function read(path)
	local stream = assert(io.open(path, "rb"))
	local content = stream:read("*a")
	stream:close()
	return content
end
local sample = read(root .. "/tests/data/repository.xml")

check("version normalization", function()
	equal(common.revision("030.00.01 rc2"), "30.0.1-rc.2")
	equal(common.revision("1.0beta3"), "1.0-beta.3")
end)
check("preview ordering", function()
	local values = { "30.0.1", "30.0.1-beta.1", "30.0.1-rc.1", "29.9", "30.0.1-alpha.9" }
	table.sort(values, common.less)
	equal(table.concat(values, ","), "29.9,30.0.1-alpha.9,30.0.1-beta.1,30.0.1-rc.1,30.0.1")
	assert(not common.less("1.0", "1.0.0"))
	assert(not common.less("1.0.0", "1.0"))
	assert(common.less("1.0.1", "1.1"))
end)
for _, value in ipairs({ "../ndk", "/ndk", "ndk/../x", "ndk;echo", "$(id)", "ndk//x", "-x", "ndk/", false }) do
	check("invalid package " .. tostring(value), function()
		rejects(function()
			common.package(value)
		end)
	end)
end
for _, value in ipairs({ "", "1..2", "1.", "1.2-x.3", "not-a-version", false, 30 }) do
	check("invalid version " .. tostring(value), function()
		rejects(function()
			common.revision(value)
		end)
	end)
end
check("mise number options", function()
	equal(common.options({ timeout = "60" }).timeout, 60)
	equal(common.options({ timeout = 60 }).timeout, 60)
end)
for _, options in ipairs({
	{ unknown = true },
	{ channel = false },
	{ channel = "dev" },
	{ timeout = true },
	{ timeout = 0 },
	{ timeout = "86401" },
	{ timeout = "1.5" },
	{ packages = false },
	{ packages = { ndk = 30 } },
	{ packages = { sdk = "36" } },
	{ repository_url = false },
}) do
	check("invalid option " .. count, function()
		rejects(function()
			common.options(options, "sdk")
		end)
	end)
end
check("standalone packages reject bundle options", function()
	rejects(function()
		common.options({ packages = {} }, "ndk")
	end)
end)
check("package versions copied and normalized", function()
	local raw = { packages = { ndk = "030.0.01 rc2" } }
	equal(common.options(raw, "sdk").packages.ndk, "30.0.1-rc.2")
	equal(raw.packages.ndk, "030.0.01 rc2")
end)
for _, url in ipairs({
	"",
	"http://example.invalid/repo",
	"https://[",
	"https:///repo",
	"https://example.invalid:bad/repo",
	"file:relative.xml",
	"file://remote.invalid/repo",
	"https://example.invalid/white space",
	"https://example.invalid:0/repo",
}) do
	check("invalid URL " .. url, function()
		rejects(function()
			common.url(url)
		end)
	end)
end
check("valid URLs", function()
	for _, url in ipairs({ "https://example.invalid/repo", "https://[::1]:443/repo", "file:///tmp/repo" }) do
		equal(common.url(url), url)
	end
end)
check("XML names, attributes, entities, and comments", function()
	local node = xml.parse(
		[=[<?xml version="1.0"?><r:root xmlns:r="test"><!-- hi --><child a='x &amp; y'>a &#65; &#x42;<![CDATA[<raw>]]></child></r:root>]=]
	)
	equal(node.name, "root")
	equal(node.children[1].attrs.a, "x & y")
	equal(node.children[1].text, "a A B<raw>")
end)
for _, source in ipairs({
	"not XML",
	"<a>",
	"<a></b>",
	"<a/><b/>",
	"<a x='1' x='2'/>",
	"<a x='1/>",
	"<!DOCTYPE a><a/>",
	"<a>&outside;</a>",
	"<a>bare &</a>",
	"<!--",
}) do
	check("invalid XML " .. source, function()
		rejects(function()
			xml.parse(source)
		end)
	end)
end
check("platform tool source and checksum", function()
	local package = catalog.parse(sample, "platform-tools", "stable", "linux", "amd64")["37.0.1"]
	equal(package.package, "platform-tools")
	equal(package.download.checksum_type, "sha1")
	assert(package.download.url:match("platform%-tools_r37.0.1%-linux.zip$"))
end)
check("SDK platform versions", function()
	local values = catalog.parse(sample, "sdk/project", "stable", "linux", "amd64")
	equal(values["36"].package, "platforms/android-36")
	equal(values["36"].revision, "2")
	equal(values["34"].revision, "3")
end)
check("raw platform and image tool names are rejected", function()
	for _, tool in ipairs({ "platforms/android-34", "system-images/android-36/google_apis/x86_64" }) do
		rejects(function()
			catalog.parse(sample, tool, "stable", "linux", "amd64")
		end)
	end
end)
check("previews excluded from stable", function()
	local stable = catalog.parse(sample, "ndk", "stable", "linux", "amd64")
	for version in pairs(stable) do
		assert(not version:find("-", 1, true))
	end
	assert(catalog.parse(sample, "ndk", "canary", "linux", "amd64")["30.0.14904198-rc.1"])
end)
check("host-specific downloads", function()
	local values = catalog.parse(sample, "cmdline-tools", "stable", "darwin", "arm64")
	assert(not values.latest)
	for _, package in pairs(values) do
		assert(package.download.url:find("arm64", 1, true))
	end
end)
check("unsupported host is rejected", function()
	rejects(function()
		catalog.parse(sample, "sdk", "stable", "unknown", "amd64")
	end)
	rejects(function()
		catalog.parse(sample, "sdk", "stable", "linux", "unknown")
	end)
end)
check("invalid package lists", function()
	for _, source in ipairs({ "not XML", "<wrong/>", "<sdk-repository/>" }) do
		rejects(function()
			catalog.parse(source, "platform-tools")
		end)
	end
end)
check("system image address", function()
	equal(
		catalog.repository_url("system-image", common.options({}, "system-image")),
		"https://dl.google.com/android/repository/sys-img/google_apis/sys-img2-3.xml"
	)
	equal(
		catalog.repository_url("system-image", common.options({ variant = "google_apis_playstore" }, "system-image")),
		"https://dl.google.com/android/repository/sys-img/google_apis_playstore/sys-img2-3.xml"
	)
end)
check("image defaults and architecture names", function()
	equal(common.options({}, "system-image").variant, "google_apis")
	for _, host in ipairs({ "amd64", "x86_64" }) do
		equal(common.image_arch(host), "x86_64")
	end
	for _, host in ipairs({ "arm64", "aarch64" }) do
		equal(common.image_arch(host), "arm64-v8a")
	end
	equal(common.options({ arch = "x86_64" }, "system-image").arch, "x86_64")
end)
check("image settings validated and scoped to images", function()
	for _, options in ipairs({ { variant = "../x" }, { variant = false }, { arch = "amd64" }, { revision = "3" } }) do
		rejects(function()
			common.options(options, "system-image")
		end)
	end
	rejects(function()
		common.options({ variant = "google_apis" }, "sdk")
	end)
end)
check("image API levels select latest revisions for variant and CPU", function()
	local source = read(root .. "/tests/data/system-images.xml")
	local images = catalog.parse(source, "system-image", "stable", "linux", "amd64")
	equal(images["36"].revision, "5")
	equal(images["36"].package, "system-images/android-36/google_apis/x86_64")
	equal(images["37"].revision, "1")
	local arm = catalog.parse(source, "system-image", "stable", "darwin", "arm64")
	equal(arm["36"].package, "system-images/android-36/google_apis/arm64-v8a")
	local play =
		catalog.parse(source, "system-image", "stable", "linux", "amd64", nil, { variant = "google_apis_playstore" })
	equal(play["36"].revision, "2")
	assert(not play["37"])
	local override = catalog.parse(source, "system-image", "stable", "darwin", "arm64", nil, { arch = "x86_64" })
	equal(override["36"].package, images["36"].package)
end)
check("CLI platforms include Linux ARM64", function()
	equal(android.platform("linux", "aarch64"), "linux_arm64")
	equal(android.platform("darwin", "arm64"), "darwin_arm64")
	equal(android.platform("linux", "amd64"), "linux_x86_64")
	rejects(function()
		android.platform("unknown", "amd64")
	end)
end)
check("CLI checksum formats", function()
	local digest = string.rep("a", 64)
	equal(android.checksum(digest), digest)
	equal(android.checksum(digest .. "  android\n"), digest)
	equal(android.checksum(digest .. "  *./android\n"), digest)
	for _, value in ipairs({ "", "abc", digest .. " trailing text" }) do
		rejects(function()
			android.checksum(value)
		end)
	end
end)
check("plan aliases, defaults, missing packages, and conflicting revisions", function()
	local previous = catalog.versions
	local ok, message = pcall(function()
		catalog.versions = function(tool)
			if common.is_sdk(tool) then
				return { ["36"] = { package = "platforms/android-36", revision = "2" } }
			elseif tool == "ndk/30.0.1" then
				return {
					["30.0.1"] = { package = tool, revision = "30.0.1" },
					["1"] = { package = tool, revision = "1" },
				}
			else
				return { ["30.0.1"] = { package = "ndk/30.0.1", revision = "30.0.1" } }
			end
		end
		equal(#android.plan("sdk", "36", common.options({})), 1)
		equal(#android.plan(
			"sdk",
			"36",
			common.options({ packages = {
				ndk = "30.0.1",
				["ndk/30.0.1"] = "30.0.1",
			} })
		), 2)
		rejects(function()
			android.plan("sdk", "99", common.options({}))
		end)
		rejects(function()
			android.plan(
				"sdk",
				"36",
				common.options({ packages = {
					ndk = "30.0.1",
					["ndk/30.0.1"] = "1",
				} })
			)
		end)
	end)
	catalog.versions = previous
	assert(ok, message)
end)

print("Passed " .. count .. " Lua checks")
return count
