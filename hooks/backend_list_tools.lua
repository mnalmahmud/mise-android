function PLUGIN:BackendListTools(ctx)
	return {
		tools = {
			{ name = "sdk", description = "Complete SDK for an Android API level" },
			{ name = "platform-tools", description = "adb and fastboot" },
			{ name = "ndk", description = "Android native development kit" },
			{ name = "build-tools", description = "Android SDK build tools" },
			{ name = "cmdline-tools", description = "Legacy Android SDK command-line tools" },
			{ name = "emulator", description = "Android emulator" },
		},
	}
end
