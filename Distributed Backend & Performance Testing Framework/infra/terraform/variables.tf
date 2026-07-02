variable "aws_region" {
  description = "AWS region in which to create load-generator nodes."
  type        = string
  default     = "ap-south-1"
}

variable "vpc_id" {
  description = "VPC that can reach Redis, the control plane, and the target."
  type        = string
}

variable "subnet_ids" {
  description = "Private or public subnet IDs used round-robin by worker nodes."
  type        = list(string)
}

variable "ami_id" {
  description = "Ubuntu 22.04/24.04 AMI ID for the selected region."
  type        = string
}

variable "instance_type" {
  description = "EC2 worker instance type."
  type        = string
  default     = "c7i.large"
}

variable "worker_count" {
  description = "Number of distributed load-generator nodes."
  type        = number
  default     = 2
  validation {
    condition     = var.worker_count >= 1 && var.worker_count <= 100
    error_message = "worker_count must be between 1 and 100."
  }
}

variable "worker_image" {
  description = "Published worker container image, including tag."
  type        = string
}

variable "redis_host" {
  description = "Redis hostname reachable from the worker subnets."
  type        = string
}

variable "redis_port" {
  description = "Redis TCP port."
  type        = number
  default     = 6379
}

variable "redis_password" {
  description = "Optional Redis password."
  type        = string
  default     = ""
  sensitive   = true
}

variable "api_base_url" {
  description = "Control-plane URL reachable from workers."
  type        = string
}

variable "worker_threads" {
  description = "Number of simultaneous test shards handled by each node."
  type        = number
  default     = 2
}

variable "ssh_key_name" {
  description = "Optional EC2 key pair name. Leave null to disable SSH access."
  type        = string
  default     = null
}

variable "ssh_cidr" {
  description = "CIDR allowed to use SSH when ssh_key_name is set."
  type        = string
  default     = "127.0.0.1/32"
}

variable "tags" {
  description = "Additional tags applied to AWS resources."
  type        = map(string)
  default     = {}
}

