#include <Arduino.h>

#define PIEZO_PIN 2
#define PWM_CHANNEL 0
#define PWM_FREQ 1000
#define PWM_RES 8
#define STRIKE_MS 50

void strike(int intensity) {
  ledcWrite(PWM_CHANNEL, intensity);
  delay(STRIKE_MS);
  ledcWrite(PWM_CHANNEL, 0);
  Serial.print('[');
  Serial.print(millis());
  Serial.print("] strike intensity=");
  Serial.print(intensity);
  Serial.print(" dur=");
  Serial.print(STRIKE_MS);
  Serial.println("ms");
}

#if 0
void demo() {
  for (int i = 1; i <= 5; i++) {
    strike(i * 50);
    delay(200);
  }
}
#endif

void note(int freq, int ms) {
  ledcSetup(PWM_CHANNEL, freq, PWM_RES);
  ledcWrite(PWM_CHANNEL, 127);
  delay(ms);
  ledcWrite(PWM_CHANNEL, 0);
  delay(30);
}

void melody() {
  note(262, 400); note(262, 400); note(392, 400); note(392, 400);
  note(440, 400); note(440, 400); note(392, 800);
  note(349, 400); note(349, 400); note(330, 400); note(330, 400);
  note(294, 400); note(294, 400); note(262, 800);
}

void setup() {
  Serial.begin(115200);
  ledcSetup(PWM_CHANNEL, PWM_FREQ, PWM_RES);
  ledcAttachPin(PIEZO_PIN, PWM_CHANNEL);
  ledcWrite(PWM_CHANNEL, 0);
  Serial.println("reduzent2026 melody test");
}

void loop() {
  melody();
  delay(1000);
}
