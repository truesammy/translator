# Manual smoke test

Run this against a test server after every change to the Discord layer. The automated
tests do not talk to Discord. Use channels `#src`, `#de`, `#fr` and a role `@Deutsch`.

| # | Do | Expect |
| --- | --- | --- |
| 1 | `/link add #src #de German @Deutsch` and `/link add #src #fr French` | Two confirmations. `/link list` shows both. |
| 2 | Post `**Bold**, _italic_, <#channel>, a link and an emoji` in `#src` | Both targets show the translation with your name and avatar, formatting and links intact. |
| 3 | Post `@everyone hello` in `#src` | `#de` pings `@Deutsch`. `#fr` shows `@everyone` as text and pings nobody. |
| 4 | Let another bot or a webhook post an embed in `#src` | Targets show the same embed (color, image, fields) with translated text. |
| 5 | Post a message with an image | The image is attached in both targets. |
| 6 | Post a message of about 1900 characters | Each target gets it complete, split in two if the translation is longer than 2000. |
| 7 | Edit the message from step 2 | Both translations change in place, without a new ping. |
| 8 | Delete the message from step 2 | Both translations disappear. |
| 9 | `/embed create #src`, fill in all five fields | The embed appears in `#src` and translated in the targets, under your name. |
| 10 | `/embed edit` with the link of that embed, change the text | The form shows the old values. Source and translations update. |
| 11 | Delete that embed in `#src` | Its translations disappear. |
| 12 | `/apikey set` with a wrong key, then a valid one, then `/apikey status` | Wrong key is refused. Valid key is saved. Status shows usage, never the key. |
| 13 | Stop the bot. In `#src` post one message, edit an older one, delete another. Start the bot. | Within a minute the new one is translated, the edit applied, the deleted one's translations removed. |
| 14 | `/link remove #src #fr` | Reply comes at once. All translations in `#fr` disappear. |
| 15 | Delete `#de` | `/link list` no longer shows it. |
| 16 | Remove the DeepL key and block outgoing network access, then post in `#src` | The message gets a ⚠️ reaction and the bot's log names each provider and its error. |
| 17 | Post a link to a tweet or a YouTube video in `#src` and wait ten seconds | Each target shows one preview made by Discord, not a second translated copy. |
| 18 | As a member without the Mention Everyone permission, post `@everyone hi` in `#src` | Nobody is pinged in any target, `@everyone` stays text. |
| 19 | Let another bot answer a slash command in `#src` | The answer is translated like any message. |
| 20 | Post in `#src`, delete the "Translator" webhook of `#de` in the channel settings, post again, then delete the first message | The second message arrives through a new webhook. The first translation is deleted too. |
| 21 | After step 20, edit a message that was posted before the webhook was deleted | Its translation in `#de` is replaced by a new one. |
| 22 | Delete one translation in `#de` by hand, then edit its original | A new translation appears in `#de`. |
| 23 | Set your server nickname to `Discord Updates` and post in `#src` | The translation is posted, under a name that looks the same. |
| 24 | Take Manage Webhooks away from the bot in `#src`, then `/embed create #src` | The bot says which permission is missing, and no form opens. |
