import sys
from cx_Freeze import setup, Executable

# Dependencies are automatically detected, but it might need
# fine tuning.
build_options = {'packages': [], 'excludes': []}

base = 'gui'

directory_table = [
    ("ProgramMenuFolder", "TARGETDIR", "."),
    ("MyProgramMenu", "ProgramMenuFolder", "MYPROG~1|My Program"),
]

msi_data = {
    "Directory": directory_table,
    "ProgId": [
        ("Prog.Id", "0.2.4", None, "Scale your avatar over OSC", "IconId", None),
    ],
    "Icon": [
        ("IconId", "resources/oscscale.ico"),
    ],
    "Shortcut": [
        ("DesktopShortcut", "DesktopFolder", "VRChat Avatar Scaler",
         "TARGETDIR", "[TARGETDIR]vrchat_avatar_scaler.exe",
         None, None, None, None, None, None, "TARGETDIR"),
        ("StartMenuShortcut", "MyProgramMenu", "VRChat Avatar Scaler",
         "TARGETDIR", "[TARGETDIR]vrchat_avatar_scaler.exe",
         None, None, None, None, None, None, "TARGETDIR"),
    ],
}

bdist_msi_options = {
    "add_to_path": True,
    "data": msi_data,
    "upgrade_code": "{bc9feaf4-f09f-46a0-ae41-9a4328756325}",
    "output_name": "VRChatAvatarScaler.msi",
}
bdist_appimage_options = {
    "target_name": "VRChatAvatarScaler.AppImage",
}

# Pick the right icon per platform
if sys.platform == "win32":
    icon = 'resources/oscscale.ico'
else:
    icon = 'resources/oscscale.svg'

executables = [
    Executable(
        'vrchat_avatar_scaler.py',
        base=base,
        icon=icon,
    ),
]

setup(name='VRChat Avatar Scaler',
      version = '0.2.4',
      description = "Change your avatar's scale over osc",
      license = "MIT License",
      options = {
      'build_exe': build_options,
      'bdist_msi': bdist_msi_options,
      'bdist_appimage': bdist_appimage_options,
      },
      executables = executables)
