param(
    [Parameter(Mandatory=$true)][string]$OutputDirectory,
    [string]$Text = 'Find your perfect fit. Shop our collection today.',
    [string]$Voice = 'Microsoft David Desktop',
    [ValidateSet('en','ru','uz')][string]$Language = 'en'
)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$speechReferences = @([System.Speech.Synthesis.SpeechSynthesizer].Assembly.Location)
$collectionsReference = Join-Path $PSHOME 'ref/System.Collections.dll'
if (Test-Path -LiteralPath $collectionsReference) { $speechReferences += $collectionsReference }
Add-Type -ReferencedAssemblies $speechReferences -TypeDefinition @'
using System;
using System.Collections.Generic;
using System.Speech.Synthesis;
using System.Speech.AudioFormat;
public class DirectorReferenceWord { public string word; public double start_ms; public double end_ms; }
public class DirectorReferencePhone { public string phoneme; public double start_ms; public double end_ms; }
public class DirectorReferenceRecorder {
    public static List<DirectorReferenceWord> Record(string path, string text, string voice) {
        var words = new List<DirectorReferenceWord>();
        var phones = new List<DirectorReferencePhone>();
        using (var synth = new SpeechSynthesizer()) {
            synth.SelectVoice(voice);
            synth.SpeakProgress += (sender,e) => words.Add(new DirectorReferenceWord {
                word=e.Text, start_ms=e.AudioPosition.TotalMilliseconds });
            synth.PhonemeReached += (sender,e) => phones.Add(new DirectorReferencePhone {
                phoneme=e.Phoneme, start_ms=e.AudioPosition.TotalMilliseconds,
                end_ms=(e.AudioPosition+e.Duration).TotalMilliseconds });
            // An explicit output format keeps callback and waveform clocks equal.
            synth.SetOutputToWaveFile(path, new SpeechAudioFormatInfo(16000, AudioBitsPerSample.Sixteen, AudioChannel.Mono));
            synth.Speak(text);
        }
        for (int i=0; i<words.Count; i++) {
            double next = i+1<words.Count ? words[i+1].start_ms : Double.MaxValue;
            double end = words[i].start_ms;
            foreach (var phone in phones) {
                // SAPI U+0004 is silence, including inter-sentence/tail padding.
                if (!String.IsNullOrWhiteSpace(phone.phoneme) && phone.phoneme[0]>=32 &&
                    phone.start_ms>=words[i].start_ms && phone.start_ms<next)
                    end=Math.Max(end, phone.end_ms);
            }
            if (end<=words[i].start_ms) throw new InvalidOperationException("No independently timed phonemes for word");
            words[i].end_ms=end;
        }
        return words;
    }
}
'@
$referenceRoot = [System.IO.Path]::GetFullPath($OutputDirectory)
New-Item -ItemType Directory -Force -Path $referenceRoot | Out-Null
$audioPath = Join-Path $referenceRoot 'reference.wav'
$referenceWords = [DirectorReferenceRecorder]::Record($audioPath, $Text, $Voice)
$approvedTokens = @($Text -split '\s+' | Where-Object { $_ })
if ($referenceWords.Count -ne $approvedTokens.Count) { throw 'Engine and approved token counts differ; annotate this recording manually' }
for ($index=0; $index -lt $approvedTokens.Count; $index++) {
    $actualToken = $referenceWords[$index].word -replace '[^\p{L}\p{N}]',''
    $expectedToken = $approvedTokens[$index] -replace '[^\p{L}\p{N}]',''
    if ($actualToken -ne $expectedToken) { throw 'Engine reference wording differs from approved narration' }
    $referenceWords[$index].word = $approvedTokens[$index]
}
$referenceFixture = @(@{
    id='independent-sapi-reference';audio_path='reference.wav';approved_text=$Text;language=$Language;
    reference_source="${Voice}: independent SpeakProgress/PhonemeReached callbacks, PCM16000, control silence excluded; generated speech, not a human corpus";
    audio_sha256=(Get-FileHash -LiteralPath $audioPath -Algorithm SHA256).Hash.ToLower();
    reference_words=@($referenceWords)
})
ConvertTo-Json -InputObject $referenceFixture -Depth 6 | Set-Content -LiteralPath (Join-Path $referenceRoot 'annotations.json') -Encoding utf8
Write-Output (Join-Path $referenceRoot 'annotations.json')
