set shell := ["sh", "-eu", "-c"]

root_dir := source_directory() + "/../.."
www_dir := root_dir + "/www"

dev:
    cd "{{ www_dir }}" && python3 -m http.server
