# ~/.bashrc - Zeal (Zealot AI host)
# Auto-attach to tmux LCD session on physical TTY or SSH

export PATH="$HOME/.local/bin:$PATH"
export TERM=linux

# Non-interactive shells (scp, rsync, ssh "command") - bail out early
case "$-" in
    *i*) ;;
    *) return 0 2>/dev/null || exit 0 ;;
esac

# Allow bypassing auto-attach with NO_AUTO_TMUX=1
if [ -n "$NO_AUTO_TMUX" ]; then
    export PS1='\[\e[36m\]\u\[\e[33m\]@\[\e[32m\]\h\[\e[0m\]:\[\e[34m\]\w\[\e[0m\]\$ '
    return 0 2>/dev/null || exit 0
fi

# Don't attach if already inside tmux
if [ -n "$TMUX" ]; then
    export PS1='\[\e[36m\]\u\[\e[33m\]@\[\e[32m\]\h\[\e[0m\]:\[\e[34m\]\w\[\e[0m\]\$ '
    return 0 2>/dev/null || exit 0
fi

should_attach() {
    # SSH connections (interactive only - already checked above)
    [ -n "$SSH_CONNECTION" ] && return 0
    # Physical console tty1/tty2
    if [ -t 0 ]; then
        TTY=$(tty)
        [[ "$TTY" == /dev/tty[12] ]] && return 0
    fi
    return 1
}

if should_attach; then
    exec ~/.local/bin/lcd-boot
fi

export PS1='\[\e[36m\]\u\[\e[33m\]@\[\e[32m\]\h\[\e[0m\]:\[\e[34m\]\w\[\e[0m\]\$ '
