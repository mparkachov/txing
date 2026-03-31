mod rig 'rig/justfile'
mod board 'board/justfile'
mod aws 'aws/justfile'
mod mcu 'mcu/justfile'
mod web 'web/justfile'

@default:
    @just --list
