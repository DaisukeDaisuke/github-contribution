# GitHub Contribution
GitHubの活動履歴を、最新年から過去年へ続く縦長の草マップにします。
<details>
<summary>草マップを表示</summary>

![profile](https://raw.githubusercontent.com/DaisukeDaisuke/github-contribution/contribution-graphs/profile-dark3.webp#gh-dark-mode-only) \
![profile](https://raw.githubusercontent.com/DaisukeDaisuke/github-contribution/contribution-graphs/profile-light3.webp#gh-light-mode-only)

</details>

[全体画像：黒](https://raw.githubusercontent.com/DaisukeDaisuke/github-contribution/contribution-graphs/profile-dark.webp) · [全体画像：白](https://raw.githubusercontent.com/DaisukeDaisuke/github-contribution/contribution-graphs/profile-light.webp) · [ダイアログHTMLをダウンロード](https://github.com/DaisukeDaisuke/github-contribution/raw/refs/heads/contribution-graphs/dialog.html)
## できること
- 対象ユーザーのアカウント作成年から実行日までを1つの表に表示。最新年が上、過去年が下。左側に年、右側に曜日を表示します。
- ライト・ダークのSVG・PNG・ロスレスWebPと、高さ600pxで下端をフェードさせたプレビューを生成します。
- ダイアログHTMLではプレビューをクリックして全体を表示。単独HTMLとしてブラウザーで開けます。
- 通常のHTMLでは日別件数の確認、日付選択、CSV・JSONの保存ができます。
- GitHub Actionsで毎月1日09:17 JSTに更新し、画像・HTML・データを`contribution-graphs`ブランチに保存します。
## 自分の草マップを作る
1. [Use this template](https://github.com/DaisukeDaisuke/github-contribution/generate)からリポジトリを作成します。
2. 作成先の**Actions → Update contribution archive → Run workflow**を実行します。対象は既定でリポジトリ所有者です。別のユーザーを指定する場合は`github_user`に入力します。
3. 生成先の`contribution-graphs`ブランチにある`embed.md`のコードを、自分のREADMEに貼り付けます。初回実行後は毎月自動更新されます。
開始年は対象ユーザーのアカウント作成年、終了日は実行日から自動で決まります。APIは1年ずつ直列取得し、各通信の完了後に1.2秒以上あけます。
## 設定
**Settings → Secrets and variables → Actions → Variables**で変更できます。
|変数|既定値|用途|
|---|---|---|
|`CONTRIBUTION_USER`|リポジトリ所有者|生成対象のGitHubユーザー名|
|`START_YEAR`|アカウント作成年|必要な場合だけ取得開始年を指定|
|`ENABLE_PAGES`|未設定|`true`でHTMLをGitHub Pagesに公開|
Pagesを使う場合は**Settings → Pages → Source**も**GitHub Actions**に設定し、Run workflowを実行します。公開先の`/`が全体表示、`/dialog.html`がダイアログです。
## 出力
[生成物一覧](https://github.com/DaisukeDaisuke/github-contribution/tree/contribution-graphs)に両テーマの全体画像・プレビュー、HTML、日別・年別・月別CSV、`data.json`、READMEに貼り付けるための`embed.md`を保存します。
ダイアログのHTMLテンプレートは[templates/dialog.html](templates/dialog.html)です。
