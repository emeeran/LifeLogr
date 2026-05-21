.PHONY: install init android ios build-android build-ios clean

install:
	cd ../frontend && npm install
	npm install @capacitor/core @capacitor/cli
	npm install @capacitor-community/sqlite

init: install
	npx cap add android
	npx cap add ios

sync:
	cd ../frontend && VITE_PLATFORM=capacitor npm run build
	npx cap sync

android: sync
	npx cap open android

ios: sync
	npx cap open ios

build-android: sync
	cd android && ./gradlew assembleRelease
	@echo "APK: android/app/build/outputs/apk/release/"

build-ios: sync
	@echo "Open Xcode and build: open ios/App/App.xcworkspace"

clean:
	rm -rf android ios node_modules
