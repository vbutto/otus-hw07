# ============================================================================
# Основные переменные
# ============================================================================

variable "cloud_id" {
  description = "Yandex Cloud cloud ID"
  type        = string
}

variable "folder_id" {
  description = "Yandex Cloud folder ID"
  type        = string
}

variable "zone" {
  description = "Default availability zone"
  type        = string
  default     = "ru-central1-a"
}

variable "sa_key_file" {
  description = "Path to service account key JSON file"
  type        = string
}

# ============================================================================
# Настройки доступа
# ============================================================================

variable "ssh_public_key" {
  description = "SSH public key content (not path to file)"
  type        = string
  default     = ""
  sensitive   = true
}

variable "my_ip" {
  description = "Your IP address in CIDR format for SSH access (e.g., 1.2.3.4/32). Leave empty to disable SSH"
  type        = string
  default     = ""
}

# ============================================================================
# Weather API настройки
# ============================================================================

variable "weather_api_key" {
  description = "API key for Yandex Weather service (https://yandex.ru/dev/weather/). Leave empty for mock data"
  type        = string
  default     = ""
  sensitive   = true
}
