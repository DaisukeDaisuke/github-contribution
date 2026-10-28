# READMEへの埋め込み
## 同じブランチに画像を置く場合
```markdown
<details>
<summary>
<img src="profile-dark3.webp#gh-dark-mode-only" alt="profile" width="800" />
<img src="profile-light3.webp#gh-light-mode-only" alt="profile" width="800" />
</summary>

![profile](profile-dark.webp#gh-dark-mode-only) \
![profile](profile-light.webp#gh-light-mode-only)

</details>

```
## 別のREADMEから専用ブランチの画像を参照する場合
```markdown
<details>
<summary>
<img src="https://raw.githubusercontent.com/DaisukeDaisuke/github-contribution/contribution-graphs/profile-dark3.webp#gh-dark-mode-only" alt="profile" width="800" />
<img src="https://raw.githubusercontent.com/DaisukeDaisuke/github-contribution/contribution-graphs/profile-light3.webp#gh-light-mode-only" alt="profile" width="800" />
</summary>

![profile](https://raw.githubusercontent.com/DaisukeDaisuke/github-contribution/contribution-graphs/profile-dark.webp#gh-dark-mode-only) \
![profile](https://raw.githubusercontent.com/DaisukeDaisuke/github-contribution/contribution-graphs/profile-light.webp#gh-light-mode-only)

</details>

```
600pxのプレビュー画像を見出しに表示し、クリックすると全体画像を展開します。
対象：DaisukeDaisuke。更新日：2026-10-28。
