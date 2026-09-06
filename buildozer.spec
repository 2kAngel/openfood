[app]
title = OpenFood
package.name = openfood
package.domain = com.openfood.app
source.dir = .
source.include_exts = py,png,jpg,kv,atlas,json
version = 0.1
requirements = python3,kivy==2.3.0,requests,pillow,plyer
orientation = portrait
fullscreen = 0
android.permissions = CAMERA,INTERNET,READ_EXTERNAL_STORAGE,WRITE_EXTERNAL_STORAGE,READ_MEDIA_IMAGES
android.api = 33
android.minapi = 21
android.ndk = 25b
android.accept_sdk_license_agreement = True
android.ant = auto
p4a.bootstrap = sdl2
p4a.port = 8000
p4a.local_recipes = ./p4a_recipes

[buildozer]
log_level = 2
warn_on_root = 0
