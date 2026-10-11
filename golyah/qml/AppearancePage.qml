import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    id: root
    objectName: "appearancePage"
    property int section: 0
    readonly property var preferences: backend.appearance
    readonly property var sample: ({
        term: "experience", lemma: "experience", entry_index: 0, sense_index: 0,
        sentence: "You may experience a delay.",
        sentence_html: "You may <font color='" + preferences.cardAccent + "'><b>experience</b></font> a delay.",
        definition_en: "To have an event, feeling, or situation happen to you.",
        usage_en: "The verb describes what someone goes through or feels.",
        sentence_translation: "Возможна задержка.",
        context_explanation: "Собеседника предупреждают о возможной задержке.",
        explain: ({}), context: ({}), sources: [], synonyms: ["undergo", "encounter"],
        examples: [{en: "She experienced a feeling of relief.", ru: "Она почувствовала облегчение."}],
        entries: [{word:"experience", lemma:"experience", pos:"v", ipa:"/ɪkˈspɪəriəns/", tags:[],
            dictionary:"", sources:[], synonyms:["undergo","encounter"], etymology:"", extra:"",
            senses:[{translation:"испытывать, переживать", examples:[]}]}]
    })
    RowLayout {
        anchors.fill: parent; spacing: 26
        ScrollView {
            objectName: "appearanceControls"
            Layout.preferredWidth: 365; Layout.maximumWidth: 400; Layout.fillHeight: true
            clip: true; contentWidth: availableWidth
            ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
            ColumnLayout {
                width: parent.width; spacing: 18
                Label { text: "Ваше пространство"; color: Theme.text; font.pixelSize: Theme.px(23); font.weight: Font.DemiBold; Layout.fillWidth: true; wrapMode: Text.Wrap }
                Label { text: "Тёмная тема. Цвета и размеры — под вас. Изменения сохраняются сразу."; color: Theme.muted; font.pixelSize: Theme.px(13); Layout.fillWidth: true; wrapMode: Text.Wrap }
                RowLayout {
                    Layout.fillWidth: true
                    SoftButton { text: "Интерфейс"; accent: root.section === 0; quiet: root.section !== 0; onClicked: root.section = 0; Layout.fillWidth: true }
                    SoftButton { text: "Карточка"; accent: root.section === 1; quiet: root.section !== 1; onClicked: root.section = 1; Layout.fillWidth: true }
                }
                ColumnLayout {
                    visible: root.section === 0; Layout.fillWidth: true; spacing: 18
                    Label { text: "АКЦЕНТ"; color: Theme.faint; font.pixelSize: Theme.px(11); font.letterSpacing: 1.4 }
                    RowLayout {
                        spacing: 10
                        Repeater {
                            model: ["#a9b7ff", "#80cdb8", "#e6b886", "#dca8dd", "#86bdef"]
                            delegate: Button {
                                required property string modelData
                                implicitWidth: 34; implicitHeight: 34
                                Accessible.name: "Акцент " + modelData
                                background: Rectangle { color: modelData; radius: 17; border.width: backend.appearance.accent === modelData ? 3 : 0; border.color: Theme.text }
                                onClicked: backend.setAppearance(JSON.stringify({accent:modelData}))
                            }
                        }
                    }
                    ColorControl { label: "Свой акцентный цвет"; settingKey: "accent"; colorValue: preferences.accent; Layout.fillWidth: true }
                    Label { text: "ТИПОГРАФИКА"; color: Theme.faint; font.pixelSize: Theme.px(11); font.letterSpacing: 1.4 }
                    Choice {
                        objectName: "uiFontChoice"; Layout.fillWidth: true; model: backend.fontFamilies
                        currentIndex: model.indexOf(preferences.uiFont)
                        onActivated: backend.setAppearance(JSON.stringify({uiFont:currentText}))
                    }
                    SettingSlider { label: "Размер текста интерфейса"; settingKey: "uiFontSize"; fromValue: 12; toValue: 20; settingValue: preferences.uiFontSize; suffix: " px"; Layout.fillWidth: true }
                    SettingSlider { label: "Ширина карточки слова"; settingKey: "cardWidth"; fromValue: 360; toValue: 840; settingValue: preferences.cardWidth; suffix: " px"; Layout.fillWidth: true }
                    Label { text: "ЗАХВАТ ЭКРАНА"; color: Theme.faint; font.pixelSize: Theme.px(11); font.letterSpacing: 1.4 }
                    SettingSlider { label: "Затемнение вокруг текста"; settingKey: "overlayDim"; fromValue: 0; toValue: 80; settingValue: preferences.overlayDim; suffix: "%"; Layout.fillWidth: true }
                    Rectangle {
                        Layout.fillWidth: true; implicitHeight: 112; radius: 12; color: "#4b5363"; clip: true
                        Rectangle { anchors.fill: parent; color: "black"; opacity: preferences.overlayDim / 100 }
                        Column { anchors.centerIn: parent; spacing: 8
                            Label { text: "Your words stay clear."; color: "white"; font.pixelSize: Theme.px(16) }
                            Label { text: "Текст остаётся без затемнения"; color: "#d4daea"; font.pixelSize: Theme.px(11) }
                        }
                    }
                    Label { text: "Распознанные строки сохраняют исходную яркость. 0% — без затемнения."; color: Theme.muted; font.pixelSize: Theme.px(12); Layout.fillWidth: true; wrapMode: Text.Wrap }
                }
                ColumnLayout {
                    visible: root.section === 1; Layout.fillWidth: true; spacing: 14
                    Label { text: "ГОТОВЫЕ ПАЛИТРЫ"; color: Theme.faint; font.pixelSize: Theme.px(11); font.letterSpacing: 1.4 }
                    RowLayout {
                        Layout.fillWidth: true; spacing: 6
                        Repeater {
                            model: [
                                {name:"Графит", cardBackground:"#20242e", cardBackgroundEnd:"#181c25", cardAccent:"#b7c3ff", cardText:"#e8ebf3", cardMuted:"#a4adbf", cardBorder:"#363d4e", cardGradient:false},
                                {name:"Сумерки", cardBackground:"#282235", cardBackgroundEnd:"#171b28", cardAccent:"#dca8dd", cardText:"#efe9f4", cardMuted:"#b5a9c5", cardBorder:"#43374f", cardGradient:true},
                                {name:"Тёплый", cardBackground:"#29241f", cardBackgroundEnd:"#1d1b19", cardAccent:"#e6b886", cardText:"#f0e9df", cardMuted:"#b8ab9c", cardBorder:"#453b32", cardGradient:false}
                            ]
                            delegate: SoftButton {
                                required property var modelData
                                Layout.fillWidth: true; text: modelData.name; font.pixelSize: Theme.px(12)
                                onClicked: { let colors = Object.assign({}, modelData); delete colors.name; backend.setAppearance(JSON.stringify(colors)) }
                            }
                        }
                    }
                    Label { text: "ШРИФТ КАРТОЧКИ"; color: Theme.faint; font.pixelSize: Theme.px(11); font.letterSpacing: 1.4 }
                    Choice {
                        objectName: "cardFontChoice"; Layout.fillWidth: true; model: backend.fontFamilies
                        currentIndex: model.indexOf(preferences.cardFont)
                        onActivated: backend.setAppearance(JSON.stringify({cardFont:currentText}))
                    }
                    SettingSlider { label: "Размер текста"; settingKey: "cardFontSize"; fromValue: 13; toValue: 24; settingValue: preferences.cardFontSize; suffix: " px"; Layout.fillWidth: true }
                    ColorControl { label: "Основной текст"; settingKey: "cardText"; colorValue: preferences.cardText; Layout.fillWidth: true }
                    ColorControl { label: "Второстепенный текст"; settingKey: "cardMuted"; colorValue: preferences.cardMuted; Layout.fillWidth: true }
                    ColorControl { label: "Выделение и акценты"; settingKey: "cardAccent"; colorValue: preferences.cardAccent; Layout.fillWidth: true }
                    ColorControl { label: "Фон карточки"; settingKey: "cardBackground"; colorValue: preferences.cardBackground; Layout.fillWidth: true }
                    Switch { objectName: "cardGradientSwitch"; text: "Мягкий градиент фона"; checked: preferences.cardGradient; onToggled: backend.setAppearance(JSON.stringify({cardGradient:checked})) }
                    ColorControl { visible: preferences.cardGradient; label: "Второй цвет фона"; settingKey: "cardBackgroundEnd"; colorValue: preferences.cardBackgroundEnd; Layout.fillWidth: true }
                    ColorControl { label: "Рамки и разделители"; settingKey: "cardBorder"; colorValue: preferences.cardBorder; Layout.fillWidth: true }
                    SettingSlider { label: "Скругление углов"; settingKey: "cardRadius"; fromValue: 0; toValue: 32; settingValue: preferences.cardRadius; suffix: " px"; Layout.fillWidth: true }
                    SettingSlider { label: "Расстояние между блоками"; settingKey: "cardSpacing"; fromValue: 8; toValue: 24; settingValue: preferences.cardSpacing; suffix: " px"; Layout.fillWidth: true }
                    SettingSlider { label: "Межстрочный интервал"; settingKey: "cardLineHeight"; fromValue: 1.1; toValue: 1.8; increment: 0.05; settingValue: preferences.cardLineHeight; Layout.fillWidth: true }
                    SoftButton { objectName: "applyAnkiAppearance"; text: "Применить оформление к Anki"; accent: true; Layout.fillWidth: true; enabled: !backend.busy; onClicked: backend.applyAnkiAppearance() }
                    Label { text: "В программе оформление меняется сразу. Эта кнопка обновляет вид всех карточек Screen Vocabulary в открытой Anki."; color: Theme.muted; font.pixelSize: Theme.px(12); Layout.fillWidth: true; wrapMode: Text.Wrap }
                }
                Rectangle { Layout.fillWidth: true; height: 1; color: Theme.border }
                SoftButton { objectName: "resetAppearance"; text: "Восстановить стандартный вид"; quiet: true; Layout.fillWidth: true; onClicked: backend.resetAppearance() }
                Item { Layout.preferredHeight: 20 }
            }
        }
        ColumnLayout {
            Layout.fillWidth: true; Layout.fillHeight: true; spacing: 12
            RowLayout {
                Layout.fillWidth: true
                Label { text: "ПРЕДПРОСМОТР"; color: Theme.faint; font.pixelSize: Theme.px(11); font.letterSpacing: 1.5 }
                Item { Layout.fillWidth: true }
                Label { text: preferences.cardWidth + " px"; color: Theme.muted; font.pixelSize: Theme.px(12) }
            }
            Rectangle {
                objectName: "appearancePreviewBackground"
                Layout.fillWidth: true; Layout.fillHeight: true; Layout.maximumWidth: preferences.cardWidth
                Layout.alignment: Qt.AlignHCenter
                radius: preferences.cardRadius; color: Theme.cardBackground; border.color: Theme.cardBorder
                gradient: preferences.cardGradient ? previewGradient : null
                Gradient { id: previewGradient; GradientStop { position:0; color:Theme.cardBackground } GradientStop { position:1; color:Theme.cardBackgroundEnd } }
                WordCard {
                    objectName: "appearancePreviewCard"
                    anchors.fill: parent; anchors.margins: 24
                    cardData: root.sample; previewOnly: true; translationVisible: true
                }
            }
            Label { text: "Живой пример: цвета, шрифт и интервалы совпадают с карточкой слова. На небольшом экране ширина ограничивается доступным местом."; color: Theme.muted; font.pixelSize: Theme.px(12); Layout.fillWidth: true; wrapMode: Text.Wrap }
        }
    }
}
