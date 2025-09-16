terraform {
  required_version = ">= 1.12.2"

  required_providers {
    yandex = {
      source  = "yandex-cloud/yandex"
      version = ">= 0.159.0"
    }
  }
}
