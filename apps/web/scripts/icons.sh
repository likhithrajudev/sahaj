#!/bin/sh
# Rebuilds the Material Symbols Rounded subset (only the icons the app uses, ~55 KB instead of several MB).
# Add a name to ICONS when you use a new icon, then run: sh scripts/icons.sh
set -e
ICONS="account_balance add_box arrow_downward arrow_forward arrow_upward badge calculate chat_bubble check check_circle
chevron_right close compare_arrows content_copy dark_mode delete_history description edit error event_available
expand_less expand_more family_restroom find_in_page graphic_eq health_and_safety hearing_disabled help history info
install_desktop install_mobile ios_share language light_mode lock menu mic mic_off pause_circle person_check play_arrow
progress_activity record_voice_over refresh remove_moderator replay restart_alt savings science search_off
shield_person south stop subtitles support_agent swipe_left sync task_alt timer touch_app translate verified_user
volume_off volume_up wifi_off"
NAMES=$(echo $ICONS | tr ' ' '\n' | sort -u | paste -sd, -)
UA="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
CSS=$(curl -fsS -A "$UA" "https://fonts.googleapis.com/css2?family=Material+Symbols+Rounded:opsz,wght,FILL,GRAD@20..48,400..600,0..1,0&icon_names=$NAMES&display=block")
URL=$(echo "$CSS" | grep -o 'https://[^)]*' | head -1)
curl -fsS "$URL" -o "$(dirname "$0")/../src/assets/fonts/material-symbols-rounded-subset.woff2"
echo "Icon subset updated ($(echo "$NAMES" | tr ',' '\n' | wc -l | tr -d ' ') icons)"
