xhost + 127.0.0.1
docker run --rm -it -p 6080:6080 -v $PWD:$PWD \
  rpg_map $PWD/$1
