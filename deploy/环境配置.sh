#!/bin/bash

set -e
set -u

# 安装并切换vim
sudo apt update && sudo apt install vim
sudo update-alternatives --config editor # 推荐选择basic


# zshrc中，添加如下命令
export EXCHANGE_API_KEY="VuG06vAzyJ4ChynTEKiWSIkIg4NcpPW91eIutCBPdj29uUQLz2pxAswEl69JRoFj"
export EXCHANGE_API_SECRET="OrZi1xfOyNJIEz2MIndnRvAv4Br4I60XWKdmI32Ctyj3lemF5DJkpRlFBc4fqU4c"
export EDITOR=vim
export VISUAL=vim


# 推荐配置ntp时间同步



