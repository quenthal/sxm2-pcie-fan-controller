#!/bin/sh
set -eu
nvidia-smi --query-gpu=index,uuid,name,temperature.gpu --format=csv,noheader,nounits
