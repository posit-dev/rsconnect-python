#!/usr/bin/env bash
set -xuo pipefail

# $1: cmdStr
# $2: targetStr
# returns success (0) or error (1)
function _confirmOutputContainsString() {
	# rsconnect write-manifest streamlit --help | grep -q "-m, --image TEXT"
	output=$($1)
	if echo ${output} | grep -q "${2}"; then
		return 0
	fi
	return 1
}

function ConfirmHelp() {
	declare -a StringArray=(
		"rsconnect write-manifest streamlit --help"
		"rsconnect write-manifest fastapi --help" 
		"rsconnect deploy streamlit --help"
		"rsconnect deploy fastapi --help" 
	)
	
	# Iterate the string array using for loop
	for val in "${StringArray[@]}"; do
		if _confirmOutputContainsString "${val}" "\-m, \-\-image TEXT"; then
			echo "worked"
		else
			echo "nope"
		fi
	done
}

# $1 bundlePath
# $2 target
# $3 image
function _confirmManifestDiff() {
	cd $1
	rm manifest.json
	rsconnect write-manifest "${2}" . 
	mv manifest.json manifest-original.json
	rsconnect write-manifest "${2}" --image "${3}" .
	if _confirmOutputContainsString "diff -u manifest.json manifest-original.json" "$3"; then
		echo "worked"
	else
		echo "nope"
	fi
	return 0
}



# _confirmManifestDiff ~/dev/connect-content/bundles/python-flaskapi api rstudio/dev-connect-duplicate



function ConfirmManifestDiff() {
	declare -a StringArray=(
		"~/dev/connect-content/bundles/python-flaskapi api"
	)
	for val in "${StringArray[@]}"; do
			set -- $val # convert the "tuple" into the param args $1 $2...
			echo $1 and $2
	done

	
	# Iterate the string array using for loop
	# for val in "${StringArray[@]}"; do
	# 	if _confirmOutputContainsString "${val}" "\-m, \-\-image TEXT"; then
	# 		echo "worked"
	# 	else
	# 		echo "nope"
	# 	fi
	# done
}

ConfirmManifestDiff


# ConfirmHelp

