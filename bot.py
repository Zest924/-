import discord
from discord import app_commands
from discord.ext import commands
import datetime
import asyncio
import os

# ==============================================================================
# 1. 最終入力モーダル（リマインド内容とメンション）
# ==============================================================================
class ReminderModal(discord.ui.Modal, title="リマインダー設定（内容入力）"):
    content = discord.ui.TextInput(
        label="リマインド内容",
        style=discord.TextStyle.paragraph,
        placeholder="通知したいメッセージを入力してください",
        required=True
    )
    target = discord.ui.TextInput(
        label="メンション相手 (ユーザーID または 空欄)",
        placeholder="特定の誰かに通知したい場合は、ユーザーID（数字）を入力してください",
        required=False
    )

    def __init__(self, target_channel: discord.TextChannel, target_datetime: datetime.datetime):
        super().__init__()
        self.target_channel = target_channel
        self.target_datetime = target_datetime

    async def on_submit(self, interaction: discord.Interaction):
        now = datetime.datetime.now()
        wait_seconds = (self.target_datetime - now).total_seconds()
        
        if wait_seconds <= 0:
            await interaction.response.send_message(
                "❌ 選択された時間はすでに過ぎています。もう一度最初からやり直してください。", 
                ephemeral=True
            )
            return

        # 日本人に馴染みのある表記で通知
        time_str = self.target_datetime.strftime("%Y年%m月%d日 %H:%M")
        await interaction.response.send_message(
            f"✅ リマインダーをセットしました！\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"📢 送信先: {self.target_channel.mention}\n"
            f"📅 予定日時: `{time_str}`\n"
            f"━━━━━━━━━━━━━━━━━━━", 
            ephemeral=True
        )

        async def run_reminder():
            await asyncio.sleep(wait_seconds)
            
            mention_text = ""
            raw_target = self.target.value.strip()
            if raw_target:
                if raw_target.isdigit():
                    mention_text = f"<@{raw_target}> "
                else:
                    mention_text = f"{raw_target} "

            send_message = f"🔔 **リマインダーのお知らせ**\n{mention_text}{self.content.value}"
            
            try:
                await self.target_channel.send(send_message)
            except discord.Forbidden:
                print(f"[エラー] {self.target_channel.name} への送信権限がありません。")
            except discord.NotFound:
                print(f"[エラー] チャンネルが見つかりません。")
            except Exception as e:
                print(f"[エラー] 予期せぬエラー: {e}")

        asyncio.create_task(run_reminder())


# ==============================================================================
# 2. 日時を選択するためのビュー
# ==============================================================================
class DateTimeSelectView(discord.ui.View):
    def __init__(self, target_channel: discord.TextChannel):
        super().__init__(timeout=180)
        self.target_channel = target_channel
        
        # 日本の曜日表記を自動追加
        weekday_ja = ["月", "火", "水", "木", "金", "土", "日"]
        today = datetime.date.today()
        date_options = []
        for i in range(7):
            day = today + datetime.timedelta(days=i)
            val = day.strftime("%Y-%m-%d")
            w_idx = day.weekday()
            label = f"{day.strftime('%Y年%m月%d日')} ({weekday_ja[w_idx]})"
            
            if i == 0:
                label = f"今日：{label}"
            elif i == 1:
                label = f"明日：{label}"
                
            date_options.append(discord.SelectOption(label=label, value=val))
            
        # 24時間すべての時間と、使い勝手の良い10分刻みの「分」を用意
        hours = [f"{h:02d}" for h in range(24)]
        minutes = [f"{m:02d}" for m in range(0, 60, 10)]
        
        hour_options = [discord.SelectOption(label=f"{h}時", value=h) for h in hours]
        minute_options = [discord.SelectOption(label=f"{m}分", value=m) for m in minutes]

        self.date_select = discord.ui.Select(placeholder="📅 日付を選択（今日から1週間分）", options=date_options)
        self.hour_select = discord.ui.Select(placeholder="⏰ 「時」を選択", options=hour_options)
        self.minute_select = discord.ui.Select(placeholder="⏱️ 「分」を選択", options=minute_options)
        
        self.add_item(self.date_select)
        self.add_item(self.hour_select)
        self.add_item(self.minute_select)
        
        self.confirm_button = discord.ui.Button(label="確定して内容入力へ進む", style=discord.ButtonStyle.green)
        self.confirm_button.callback = self.on_confirm
        self.add_item(self.confirm_button)

    async def on_confirm(self, interaction: discord.Interaction):
        if not self.date_select.values or not self.hour_select.values or not self.minute_select.values:
            await interaction.response.send_message("❌ 日付、時、分をすべて選択してください。", ephemeral=True)
            return
            
        date_str = self.date_select.values
        hour_str = self.hour_select.values
        minute_str = self.minute_select.values
        
        try:
            target_datetime = datetime.datetime.strptime(f"{date_str} {hour_str}:{minute_str}", "%Y-%m-%d %H:%M")
        except ValueError:
            await interaction.response.send_message("❌ 日時の変換に失敗しました。", ephemeral=True)
            return
            
        if target_datetime <= datetime.datetime.now():
            await interaction.response.send_message("❌ 未来の日時を選択してください（過去の時間は指定できません）。", ephemeral=True)
            return

        await interaction.response.send_modal(ReminderModal(target_channel=self.target_channel, target_datetime=target_datetime))


# ==============================================================================
# 3. 最初のチャンネル選択メニュー
# ==============================================================================
class ReminderChannelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.select(
        cls=discord.ui.ChannelSelect,
        placeholder="通知を送信するチャンネルを選んでください",
        channel_types=[discord.ChannelType.text],
        min_values=1,
        max_values=1
    )
    async def select_channel(self, interaction: discord.Interaction, select: discord.ui.ChannelSelect):
        chosen_channel = select.values
        
        next_view = DateTimeSelectView(target_channel=chosen_channel)
        await interaction.response.send_message(
            f"📍 送信先チャンネル: {chosen_channel.mention}\n続いて、通知したい日時を選択してください。", 
            view=next_view, 
            ephemeral=True
        )


# ==============================================================================
# 4. Bot本体の定義
# ==============================================================================
class MyBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        await self.tree.sync()
        print("🤖 スラッシュコマンドの同期が完了しました。")

bot = MyBot()

@bot.tree.command(name="reminder", description="画面に従ってリマインダーを直感的に設定できます")
async def reminder(interaction: discord.Interaction):
    view = ReminderChannelView()
    await interaction.response.send_message(
        "リマインダーを設定します。まずは通知を送りたいチャンネルを選択してください：", 
        view=view, 
        ephemeral=True
    )

# 🔒 GitHub公開用の安全なトークン読み込み処理
TOKEN = os.getenv("DISCORD_BOT_TOKEN")

if TOKEN:
    bot.run(TOKEN)
else:
    print("❌ エラー: 環境変数 'DISCORD_BOT_TOKEN' が設定されていません。")
