#!/bin/sh
# 下載播放器使用的開源字型（SIL OFL）至 assets/fonts
set -e
cd "$(dirname "$0")/assets/fonts"
curl -sSL -o Huninn.ttf https://fonts.gstatic.com/s/huninn/v9/OpNNnoINg9bQ4xkpjg.ttf
curl -sSL -o NotoSansTC-900.ttf https://fonts.gstatic.com/s/notosanstc/v40/-nFuOG829Oofr2wohFbTp9ifNAn722rq0MXz7wm1_Co.ttf
